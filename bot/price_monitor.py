"""
bot/price_monitor.py
Monitors a symbol's price using Binance WebSocket streams.
When the current price reaches or exceeds the target price it fires
an on_trigger callback (which places the sell order).
"""

import threading
import logging
import time
from binance import ThreadedWebsocketManager
from bot.binance_client import get_client

log = logging.getLogger(__name__)


class PriceMonitor:
    """
    Streams real-time prices for a symbol via WebSocket and fires a callback
    when the target sell price is reached.

    Usage:
        monitor = PriceMonitor(
            symbol="BTCUSDT",
            target_price=65000.0,
            quantity=0.001,
            testnet=True,
            on_price=lambda p: ...,
            on_trigger=lambda sym, qty: ...,
            on_error=lambda e: ...,
        )
        monitor.start()
        # later…
        monitor.stop()
    """

    def __init__(
        self,
        symbol: str,
        buy_price: float,
        quantity: float,
        testnet: bool,
        on_price,                  # callback(price: float)
        on_trigger,                # callback(symbol: str, quantity: float) -> order dict
        on_error,                  # callback(error: str)
        initial_price: float = 0.0,# starting price for percentage drop calculation
        drop_percentage: float = 0.0, # e.g. 5.0 for 5% drop trigger
        min_profit_pct: float = 0.2,  # e.g. 0.2 for +0.2% profit above buy price
        on_drop=None,              # callback(symbol, current_price, initial_price, actual_drop_pct)
        api_key: str | None = None,
        api_secret: str | None = None,
        target_price: float | None = None, # optional backwards-compatibility alias
    ):
        self.symbol = symbol.upper()
        self.buy_price = buy_price if buy_price > 0 else (target_price or 0.0)
        self.target_price = self.buy_price
        self.quantity = quantity
        self.testnet = testnet
        self.on_price = on_price
        self.on_trigger = on_trigger
        self.on_error = on_error
        self.initial_price = initial_price if initial_price > 0 else self.buy_price
        self.drop_percentage = drop_percentage
        self.min_profit_pct = min_profit_pct
        self.on_drop = on_drop
        self.api_key = api_key
        self.api_secret = api_secret

        self._triggered = False
        self._drop_alert_fired = False
        self._running = False
        self._twm: ThreadedWebsocketManager | None = None
        self._thread: threading.Thread | None = None
        self._last_tick_time: float = 0.0  # Watchdog: timestamp of last price tick

    # ── public API ────────────────────────────────────────────────────────

    def start(self):
        """Start the WebSocket price stream in a background thread."""
        if self._running:
            return
        self._triggered = False
        self._running = True
        self._last_tick_time = time.time()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        log.info(
            f"[PriceMonitor] Started monitoring {self.symbol} @ buy price {self.buy_price} "
            f"(real-time ~0.2s stream, triggers sell when price >= +{self.min_profit_pct}% higher)"
        )

    def stop(self):
        """Stop the WebSocket stream."""
        self._running = False
        if self._twm:
            try:
                self._twm.stop()
            except Exception:
                pass
        log.info("[PriceMonitor] Stopped.")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_triggered(self) -> bool:
        return self._triggered

    # ── internals ─────────────────────────────────────────────────────────

    def _run(self):
        """Main loop: connect WebSocket, handle messages."""
        try:
            client = get_client(testnet=self.testnet, api_key=self.api_key, api_secret=self.api_secret)
            # Always use LIVE WebSocket for price streaming (public market data)
            self._twm = ThreadedWebsocketManager(
                api_key=client.API_KEY,
                api_secret=client.API_SECRET,
                testnet=False,
            )
            self._twm.start()

            # Use real-time aggTrade WebSocket stream (~0.1s - 0.2s updates on every trade)
            stream_name = self._twm.start_aggtrade_socket(
                callback=self._handle_message,
                symbol=self.symbol,
            )

            log.info(f"[PriceMonitor] Real-time trade stream started: {stream_name}")

            # Keep thread alive while running, with watchdog check every 2 seconds
            while self._running:
                time.sleep(2)
                # Watchdog: if no tick received for 60 seconds, log a warning
                if self._running and (time.time() - self._last_tick_time) > 60:
                    log.warning(
                        f"[PriceMonitor] Watchdog: No price ticks received for {self.symbol} in 60s. "
                        "Stream may be stalled."
                    )
                    self._last_tick_time = time.time()  # Reset to avoid spamming

        except Exception as exc:
            if self._running and not self._triggered:
                log.error(f"[PriceMonitor] Stream error: {exc}")
                self.on_error(str(exc))
            self._running = False
        finally:
            if self._twm:
                try:
                    self._twm.stop()
                except Exception:
                    pass

    def _handle_message(self, msg: dict):
        """Process each incoming WebSocket tick."""
        if not self._running or self._triggered:
            return

        event_type = msg.get("e", "")
        if event_type == "error":
            # Ignore disconnection / teardown messages when stopping or triggered
            if self._running and not self._triggered:
                err_msg = str(msg.get("m", msg))
                if "reconnect" not in err_msg.lower():
                    self.on_error(err_msg)
            return

        # Support 'p' (aggTrade/trade price), 'c' (miniTicker close price), 'b' (bookTicker bid)
        try:
            raw_p = msg.get("p", msg.get("c", msg.get("b", 0)))
            price = float(raw_p)
        except (ValueError, TypeError):
            return

        if price <= 0:
            return

        # Update watchdog timestamp
        self._last_tick_time = time.time()

        # Fire price update to dashboard
        self.on_price(price)

        # Check price drop condition (e.g. 5% lower than initial price)
        if self.drop_percentage > 0 and self.initial_price > 0 and not self._drop_alert_fired:
            threshold = self.initial_price * (1.0 - self.drop_percentage / 100.0)
            if price <= threshold:
                self._drop_alert_fired = True
                actual_drop_pct = ((self.initial_price - price) / self.initial_price) * 100.0
                log.info(
                    f"[PriceMonitor] PRICE DROP ALERT! {self.symbol} price {price} dropped {actual_drop_pct:.2f}% (>= {self.drop_percentage}%)"
                )
                if self.on_drop:
                    # Offload on_drop to background thread to avoid blocking WebSocket
                    threading.Thread(
                        target=self._safe_callback,
                        args=("on_drop", self.on_drop, self.symbol, price, self.initial_price, actual_drop_pct),
                        daemon=True,
                    ).start()

        # Check trigger condition: price higher than buy price by at least min_profit_pct (e.g. +0.1%)
        trigger_threshold = self.buy_price * (1.0 + self.min_profit_pct / 100.0) if self.buy_price > 0 else 0.0
        if self.buy_price > 0 and price >= trigger_threshold:
            self._triggered = True
            self._running = False
            gain_pct = ((price - self.buy_price) / self.buy_price) * 100.0
            log.info(
                f"[PriceMonitor] TRIGGER! {self.symbol} price {price} is higher than buy price {self.buy_price} "
                f"(+{gain_pct:.2f}% >= +{self.min_profit_pct}%) -> SELLING NOW"
            )
            # Offload on_trigger to background thread to avoid blocking WebSocket
            threading.Thread(
                target=self._safe_callback,
                args=("on_trigger", self.on_trigger, self.symbol, self.quantity, price),
                daemon=True,
            ).start()

    def _safe_callback(self, name: str, callback, *args):
        """Execute a callback safely in a background thread."""
        try:
            result = callback(*args)
            if name == "on_trigger":
                log.info(f"[PriceMonitor] {name} completed: {result}")
        except Exception as exc:
            log.error(f"[PriceMonitor] Error in {name} callback: {exc}")
            self.on_error(f"{name} failed: {exc}")
