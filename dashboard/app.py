"""
dashboard/app.py
Flask + Socket.IO web dashboard for the Binance Sell Bot.
Handles REST API endpoints and real-time socket events.
"""

import logging
import sys
import os
import time
import requests
from datetime import datetime

# Add project root to path so sub-packages resolve correctly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit

from config.settings import settings
from bot.binance_client import get_client, get_current_price, get_symbol_info
from bot.price_monitor import PriceMonitor
from bot.order_manager import place_market_sell, place_market_buy_quote, convert_coin_to_top_gainer
from bot.strategy import find_top_gainer_4h

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

# ── Flask / SocketIO setup ────────────────────────────────────────────────────
app = Flask(__name__)
app.config["SECRET_KEY"] = settings.FLASK_SECRET_KEY
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ── Global bot state ──────────────────────────────────────────────────────────
_monitor: PriceMonitor | None = None
_trade_log: list[dict] = []          # chronological list of log entries
_bot_config: dict = {}               # last submitted config
_session_traded_symbols: set[str] = set() # tracked traded symbols in session


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _push_log(level: str, message: str):
    """Append an entry to the trade log and push it to all connected clients."""
    entry = {"level": level, "message": message}
    _trade_log.append(entry)
    socketio.emit("log_entry", entry)


def _push_status(status: str, extra: dict | None = None):
    """Emit a bot status update to all connected clients."""
    payload = {"status": status}
    if extra:
        payload.update(extra)
    socketio.emit("bot_status", payload)


# ══════════════════════════════════════════════════════════════════════════════
# Socket.IO events
# ══════════════════════════════════════════════════════════════════════════════

@socketio.on("connect")
def on_connect():
    """Send current state to newly connected client."""
    status = "idle"
    if _monitor:
        if _monitor.is_triggered:
            status = "triggered"
        elif _monitor.is_running:
            status = "running"

    emit("bot_status", {"status": status, "config": _bot_config})
    for entry in _trade_log[-100:]:   # send last 100 log lines
        emit("log_entry", entry)


# ══════════════════════════════════════════════════════════════════════════════
# REST API
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/price", methods=["GET"])
def api_price():
    """Quick WebSocket price check for a symbol."""
    symbol = request.args.get("symbol", "BTCUSDT").upper()
    try:
        price = get_current_price(symbol)
        return jsonify({"symbol": symbol, "price": price})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/verify-keys", methods=["POST"])
def api_verify_keys():
    """Verify Binance API credentials and fetch account balance."""
    data = request.get_json(force=True)
    api_key = str(data.get("api_key", "")).strip()
    api_secret = str(data.get("api_secret", "")).strip()
    testnet = bool(data.get("testnet", True))

    try:
        client = get_client(testnet=testnet, api_key=api_key, api_secret=api_secret)
        account_info = client.get_account()
        can_trade = account_info.get("canTrade", False)
        
        # Extract non-zero balances
        balances = []
        usdt_balance = 0.0
        for b in account_info.get("balances", []):
            free = float(b.get("free", 0))
            locked = float(b.get("locked", 0))
            total = free + locked
            if total > 0:
                balances.append({
                    "asset": b["asset"],
                    "free": free,
                    "locked": locked,
                    "total": total,
                })
            if b["asset"] == "USDT":
                usdt_balance = free

        return jsonify({
            "ok": True,
            "can_trade": can_trade,
            "usdt_balance": usdt_balance,
            "balances": balances[:15],
            "mode": "Testnet" if testnet else "Live",
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.route("/api/start", methods=["POST"])
def api_start():
    """Start the price monitor / sell bot."""
    global _monitor, _bot_config, _trade_log, _session_traded_symbols

    data = request.get_json(force=True)

    # ── Credentials from frontend (optional fallback to .env) ───────────
    api_key = str(data.get("api_key", "")).strip()
    api_secret = str(data.get("api_secret", "")).strip()

    # ── Validate input ──────────────────────────────────────────────────
    symbol = str(data.get("symbol", "")).strip().upper()
    try:
        raw_target_val = float(data.get("target_price", 0))
        raw_quantity_val = float(data.get("quantity", 0))
        drop_percentage = float(data.get("drop_percentage", settings.DEFAULT_DROP_PERCENTAGE))
    except (ValueError, TypeError):
        return jsonify({"error": "target_price, quantity, and drop_percentage must be numbers."}), 400

    target_type = str(data.get("target_type", "price")).strip().lower()
    quantity_type = str(data.get("quantity_type", "usdt")).strip().lower()
    n8n_webhook_url = str(data.get("n8n_webhook_url", settings.N8N_WEBHOOK_URL)).strip()
    auto_convert: bool = bool(data.get("auto_convert", settings.AUTO_CONVERT_ON_DROP))
    auto_restart_on_trigger: bool = bool(data.get("auto_restart_on_trigger", settings.AUTO_RESTART_ON_TRIGGER))
    testnet: bool = bool(data.get("testnet", True))

    if not symbol:
        return jsonify({"error": "symbol is required."}), 400
    if raw_target_val <= 0:
        return jsonify({"error": "target_price or percentage must be greater than 0."}), 400
    if raw_quantity_val <= 0:
        return jsonify({"error": "quantity or USDT amount must be greater than 0."}), 400
    if drop_percentage < 0:
        return jsonify({"error": "drop_percentage must be >= 0."}), 400

    # ── Stop any existing monitor ───────────────────────────────────────
    if _monitor and _monitor.is_running:
        _monitor.stop()
        _push_log("warning", "Previous monitor stopped.")

    # ── Authenticate client & validate symbol ───────────────────────────
    try:
        client = get_client(testnet=testnet, api_key=api_key, api_secret=api_secret)
        get_symbol_info(client, symbol)
        current_price = get_current_price(symbol, client=client)
    except Exception as exc:
        return jsonify({"error": f"Failed to initialize client for {symbol}: {exc}"}), 400

    # Compute target price and target percentage based on target_type
    if target_type == "percentage":
        target_percentage = raw_target_val
        target_price = current_price * (1.0 + target_percentage / 100.0)
    else:
        target_price = raw_target_val
        target_percentage = ((target_price - current_price) / current_price) * 100.0 if current_price > 0 else 0.0

    # Compute quantity in base asset and USDT amount based on quantity_type
    if quantity_type == "usdt":
        usdt_amount = raw_quantity_val
        quantity = usdt_amount / current_price if current_price > 0 else 0.0
    else:
        quantity = raw_quantity_val
        usdt_amount = quantity * current_price

    _trade_log = []
    _session_traded_symbols = {symbol}
    _bot_config = {
        "symbol": symbol,
        "target_type": target_type,
        "target_percentage": round(target_percentage, 2),
        "target_price": round(target_price, 6),
        "quantity_type": quantity_type,
        "usdt_amount": round(usdt_amount, 2),
        "quantity": quantity,
        "testnet": testnet,
        "current_price": current_price,
        "drop_percentage": drop_percentage,
        "auto_convert": auto_convert,
        "auto_restart_on_trigger": auto_restart_on_trigger,
        "n8n_webhook_url": n8n_webhook_url,
    }

    mode_label = "TESTNET" if testnet else "LIVE"
    _push_log("info", f"[{mode_label}] Bot started — {symbol}")
    _push_log("info", f"Target mode        : {'Percentage (+' + str(round(target_percentage, 2)) + '%)' if target_type == 'percentage' else 'Exact Price ($' + str(round(target_price, 6)) + ')'}")
    _push_log("info", f"Calculated target  : {target_price:,.6f}")
    _push_log("info", f"Amount to sell     : ${usdt_amount:,.2f} USDT ({quantity:,.6f} {symbol})")
    _push_log("info", f"Current price      : {current_price:,.6f}")
    restart_action_desc = "Auto-Restart Bot" if auto_restart_on_trigger else "Stop Trading"
    _push_log("info", f"Goal reached action: {restart_action_desc}")
    if drop_percentage > 0:
        drop_price = current_price * (1.0 - drop_percentage / 100.0)
        action_desc = "Auto-Convert & Continuous Loop" if auto_convert else "Alert Only"
        _push_log("info", f"Price drop action  : {drop_percentage}% drop → {action_desc} (≤ {drop_price:,.6f})")
    if n8n_webhook_url:
        _push_log("info", f"n8n Webhook URL    : {n8n_webhook_url}")

    # Helper function to launch monitor for current or newly converted symbol
    def start_monitoring_for_symbol(
        current_sym: str,
        current_qty: float,
        current_init_price: float,
        current_target_price: float,
    ):
        global _monitor

        def on_price(price: float):
            socketio.emit("price_update", {
                "symbol": current_sym,
                "price": price,
                "target": current_target_price,
            })

        def on_trigger(sym: str, qty: float):
            _push_log("success", f"🎯 PROFIT TARGET REACHED for {sym}! Placing MARKET SELL for {qty} {sym} …")
            order = place_market_sell(client, sym, qty)
            _push_log(
                "success",
                f"🎉 TARGET SECURED! Sold {qty} {sym} | Order ID={order.get('orderId')} | Status={order.get('status')}.",
            )

            if auto_restart_on_trigger:
                _push_log("info", f"🔄 AUTO-RESTART ENABLED: Restarting bot for {sym} with same settings …")
                time.sleep(1.0)
                try:
                    new_price = get_current_price(sym, client=client)
                except Exception:
                    new_price = current_init_price

                if target_type == "percentage":
                    new_target = round(new_price * (1.0 + target_percentage / 100.0), 6)
                else:
                    ratio = current_target_price / current_init_price if current_init_price > 0 else (1.0 + target_percentage / 100.0)
                    if ratio <= 1.0:
                        ratio = 1.10
                    new_target = round(new_price * ratio, 6)

                _bot_config.update({
                    "symbol": sym,
                    "current_price": new_price,
                    "target_price": new_target,
                })

                _push_log(
                    "info",
                    f"🚀 RESTARTED AUTOMATICALLY: Monitoring {sym} @ initial ${new_price:,.6f} (New Target: ${new_target:,.6f})"
                )

                start_monitoring_for_symbol(
                    current_sym=sym,
                    current_qty=qty,
                    current_init_price=new_price,
                    current_target_price=new_target,
                )
            else:
                _push_status("triggered")
                _push_log("info", "🏁 Trading completed — bot stopped until manually restarted.")
                if _monitor:
                    _monitor.stop()

            return order

        def on_drop(sym: str, cur_p: float, init_p: float, actual_drop_pct: float):
            global _session_traded_symbols

            _push_log(
                "warning",
                f"🚨 PRICE DROP DETECTED! {sym} dropped {actual_drop_pct:.2f}% "
                f"(from {init_p:,.4f} to {cur_p:,.4f})!"
            )

            payload = {
                "event": "PRICE_DROP_ALERT",
                "symbol": sym,
                "initial_price": init_p,
                "current_price": cur_p,
                "target_price": current_target_price,
                "requested_drop_percentage": drop_percentage,
                "actual_drop_percentage": round(actual_drop_pct, 2),
                "auto_convert_enabled": auto_convert,
                "timestamp": datetime.now().isoformat(),
            }

            # ── Auto-Convert logic: Sell current coin & Buy Top 4H Gainer ──
            if auto_convert:
                # Check if exclusion list reached 5 coins and reset
                if len(_session_traded_symbols) >= 5:
                    _push_log(
                        "info",
                        f"🧹 Excluded coins list reached {len(_session_traded_symbols)} coins ({list(_session_traded_symbols)}). "
                        f"Resetting exclusion list to current symbol ({sym})!"
                    )
                    _session_traded_symbols.clear()
                    _session_traded_symbols.add(sym)

                _push_log("warning", f"🔄 Auto-Convert Enabled: Scanning for Top 4H Gainer coin on Binance (Excluding {list(_session_traded_symbols)}) …")
                try:
                    top_gainer = find_top_gainer_4h(client=client, exclude_symbols=_session_traded_symbols)
                    top_sym = top_gainer["symbol"]
                    top_gain_pct = top_gainer["gain_4h_pct"]
                    top_price = top_gainer["current_price"]
                    _session_traded_symbols.add(top_sym)

                    if len(_session_traded_symbols) >= 5:
                        _push_log(
                            "info",
                            f"🧹 Excluded list reached 5 coins after adding {top_sym}. "
                            f"Resetting list to only include current holding ({top_sym})."
                        )
                        _session_traded_symbols.clear()
                        _session_traded_symbols.add(top_sym)

                    _push_log("info", f"🏆 Found Top 4H Gainer: {top_sym} (+{top_gain_pct}% 4H gain)")

                    _push_log("warning", f"💸 Executing Conversion: Selling {current_qty} {sym} → Buying {top_sym} …")
                    conversion = convert_coin_to_top_gainer(client, sym, current_qty, top_sym)

                    new_bought_qty = conversion["bought_quantity"]

                    _push_log(
                        "success",
                        f"✅ CONVERSION SUCCESSFUL! "
                        f"Sold {sym} for ${conversion['usdt_proceeds']:.2f} USDT → "
                        f"Bought {new_bought_qty} {top_sym}!"
                    )

                    payload.update({
                        "event": "AUTO_CONVERT_SUCCESS",
                        "converted_to_symbol": top_sym,
                        "top_gainer_4h_gain_pct": top_gain_pct,
                        "sold_quantity": current_qty,
                        "usdt_proceeds": conversion["usdt_proceeds"],
                        "bought_quantity": new_bought_qty,
                        "sell_order_id": conversion["sell_order_id"],
                        "buy_order_id": conversion["buy_order_id"],
                    })

                    # Calculate new target price based on Target Profit % or target ratio
                    if target_type == "percentage":
                        new_target_price = round(top_price * (1.0 + target_percentage / 100.0), 6)
                    else:
                        target_ratio = current_target_price / current_init_price if current_init_price > 0 else (1.0 + target_percentage / 100.0)
                        if target_ratio <= 1.0:
                            target_ratio = 1.10
                        new_target_price = round(top_price * target_ratio, 6)

                    # Update global bot config for new coin
                    _bot_config.update({
                        "symbol": top_sym,
                        "target_type": target_type,
                        "target_percentage": round(target_percentage, 2),
                        "quantity": new_bought_qty,
                        "current_price": top_price,
                        "target_price": new_target_price,
                        "drop_percentage": drop_percentage,
                        "auto_convert": True,
                        "n8n_webhook_url": n8n_webhook_url,
                    })

                    _push_log(
                        "info",
                        f"🔄 CONTINUOUS LOOP: Re-starting live WebSocket stream for {top_sym} "
                        f"(Amount: {new_bought_qty}, Target: ${new_target_price:,.6f} [+{round(target_percentage, 2)}%], Drop: {drop_percentage}%)"
                    )

                    # Re-launch monitor continuously for the new coin
                    start_monitoring_for_symbol(
                        current_sym=top_sym,
                        current_qty=new_bought_qty,
                        current_init_price=top_price,
                        current_target_price=new_target_price,
                    )

                except Exception as exc:
                    _push_log("error", f"❌ Auto-Conversion Failed: {exc}")
                    payload["event"] = "AUTO_CONVERT_FAILED"
                    payload["error"] = str(exc)

            socketio.emit("price_drop_alert", payload)

            if n8n_webhook_url:
                _push_log("info", f"📡 Dispatching webhook to n8n ({n8n_webhook_url}) …")
                try:
                    resp = requests.post(n8n_webhook_url, json=payload, timeout=10)
                    if resp.status_code in (200, 201, 202, 204):
                        _push_log("success", f"✅ n8n Webhook delivered successfully! (HTTP {resp.status_code})")
                    else:
                        _push_log("error", f"⚠️ n8n Webhook failed with HTTP {resp.status_code}: {resp.text[:100]}")
                except Exception as exc:
                    _push_log("error", f"❌ Error sending n8n webhook: {exc}")
            else:
                _push_log("warning", "⚠️ No n8n Webhook URL set. Alert logged to dashboard only.")

        def on_error(err: str):
            _push_log("error", f"❌ Error: {err}")
            _push_status("error")

        if _monitor and _monitor.is_running:
            _monitor.stop()

        _monitor = PriceMonitor(
            symbol=current_sym,
            target_price=current_target_price,
            quantity=current_qty,
            testnet=testnet,
            on_price=on_price,
            on_trigger=on_trigger,
            on_error=on_error,
            initial_price=current_init_price,
            drop_percentage=drop_percentage,
            on_drop=on_drop,
            api_key=api_key,
            api_secret=api_secret,
        )
        _monitor.start()
        _push_status("running", {"config": _bot_config})

    # Start initial monitoring
    start_monitoring_for_symbol(
        current_sym=symbol,
        current_qty=quantity,
        current_init_price=current_price,
        current_target_price=target_price,
    )

    return jsonify({"ok": True, "current_price": current_price})



@app.route("/api/stop", methods=["POST"])
def api_stop():
    """Stop the running price monitor."""
    global _monitor
    if _monitor and _monitor.is_running:
        _monitor.stop()
        _push_log("warning", "Bot manually stopped by user.")
        _push_status("idle")
    return jsonify({"ok": True})


@app.route("/api/status", methods=["GET"])
def api_status():
    """Return current bot status."""
    status = "idle"
    if _monitor:
        if _monitor.is_triggered:
            status = "triggered"
        elif _monitor.is_running:
            status = "running"
    return jsonify({"status": status, "config": _bot_config})
