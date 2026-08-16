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
        target_price: float,
        quantity: float,
        testnet: bool,
        on_price,                  # callback(price: float)
        on_trigger,                # callback(symbol: str, quantity: float) -> order dict
        on_error,                  # callback(error: str)
        initial_price: float = 0.0,# starting price for percentage drop calculation
        drop_percentage: float = 0.0, # e.g. 5.0 for 5% drop trigger
        on_drop=None,              # callback(symbol, current_price, initial_price, actual_drop_pct)
    ):
        self.symbol = symbol.upper()
        self.target_price = target_price
        self.quantity = quantity
        self.testnet = testnet
        self.on_price = on_price
        self.on_trigger = on_trigger
        self.on_error = on_error
        self.initial_price = initial_price
        self.drop_percentage = drop_percentage
        self.on_drop = on_drop

        self._triggered = False
        self._drop_alert_fired = False
        self._running = False
        self._twm: ThreadedWebsocketManager | None = None
        self._thread: threading.Thread | None = None

    # ── public API ────────────────────────────────────────────────────────

    def start(self):
        """Start the WebSocket price stream in a background thread."""
        if self._running:
            return
        self._triggered = False
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        log.info(f"[PriceMonitor] Started monitoring {self.symbol} @ target {self.target_price}")

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
            client = get_client(testnet=self.testnet)
            # Always use LIVE WebSocket for price streaming (public market data)
            self._twm = ThreadedWebsocketManager(
                api_key=client.API_KEY,
                api_secret=client.API_SECRET,
                testnet=False,
            )
            self._twm.start()

            # Use individual symbol miniTicker WebSocket stream (~1s updates)
            stream_name = self._twm.start_symbol_miniticker_socket(
                callback=self._handle_message,
                symbol=self.symbol,
            )

            log.info(f"[PriceMonitor] WebSocket stream started: {stream_name}")

            # Keep thread alive while running
            while self._running:
                time.sleep(0.5)

        except Exception as exc:
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

        # MiniTicker payload uses 'c' for close/current price
        event_type = msg.get("e", "")
        if event_type == "error":
            self.on_error(str(msg))
            return

        try:
            price = float(msg.get("c", 0))
        except (ValueError, TypeError):
            return

        if price <= 0:
            return

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
                    try:
                        self.on_drop(self.symbol, price, self.initial_price, actual_drop_pct)
                    except Exception as exc:
                        log.error(f"[PriceMonitor] Error firing on_drop callback: {exc}")

        # Check trigger condition: price reached or exceeded target
        if price >= self.target_price:
            self._triggered = True
            self._running = False
            log.info(
                f"[PriceMonitor] TRIGGER! {self.symbol} price {price} >= target {self.target_price}"
            )
            try:
                order = self.on_trigger(self.symbol, self.quantity)
                log.info(f"[PriceMonitor] Sell order placed: {order}")
            except Exception as exc:
                log.error(f"[PriceMonitor] Sell order failed: {exc}")
                self.on_error(f"Sell order failed: {exc}")
