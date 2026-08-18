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
from bot.strategy import find_top_gainer_1h

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
            "balances": balances[:25],
            "mode": "Testnet" if testnet else "Live",
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.route("/api/balance", methods=["POST"])
def api_balance():
    """Fetch real-time spot wallet balances for USDT and a target symbol."""
    data = request.get_json(force=True)
    api_key = str(data.get("api_key", "")).strip()
    api_secret = str(data.get("api_secret", "")).strip()
    testnet = bool(data.get("testnet", True))
    symbol = str(data.get("symbol", "")).strip().upper()

    try:
        client = get_client(testnet=testnet, api_key=api_key, api_secret=api_secret)
        account_info = client.get_account()
        
        balances_map = {b["asset"]: float(b.get("free", 0)) for b in account_info.get("balances", [])}
        usdt_free = balances_map.get("USDT", 0.0)

        coin_asset = ""
        coin_free = 0.0
        coin_value_usdt = 0.0
        current_price = 0.0

        if symbol:
            try:
                info = get_symbol_info(client, symbol)
                coin_asset = info.get("baseAsset", symbol.replace("USDT", ""))
            except Exception:
                coin_asset = symbol.replace("USDT", "")

            coin_free = balances_map.get(coin_asset, 0.0)
            try:
                current_price = get_current_price(symbol, client=client)
                coin_value_usdt = coin_free * current_price
            except Exception:
                pass

        # Return list of non-zero assets
        non_zero = []
        for b in account_info.get("balances", []):
            f = float(b.get("free", 0))
            l = float(b.get("locked", 0))
            if f > 0 or l > 0:
                non_zero.append({"asset": b["asset"], "free": f, "locked": l})

        return jsonify({
            "ok": True,
            "usdt_free": usdt_free,
            "coin_asset": coin_asset,
            "coin_free": coin_free,
            "coin_value_usdt": coin_value_usdt,
            "current_price": current_price,
            "all_balances": non_zero[:20],
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.route("/api/quick-buy", methods=["POST"])
def api_quick_buy():
    """Place a custom market buy order (choose target coin, quote paying coin, and custom amount)."""
    data = request.get_json(force=True)
    api_key = str(data.get("api_key", "")).strip()
    api_secret = str(data.get("api_secret", "")).strip()
    testnet = bool(data.get("testnet", True))
    
    # Can accept full symbol e.g. BARUSDT or split buy_coin + pay_coin
    buy_coin = str(data.get("buy_coin", "")).strip().upper()
    pay_coin = str(data.get("pay_coin", "USDT")).strip().upper()
    raw_symbol = str(data.get("symbol", "")).strip().upper()

    if raw_symbol:
        symbol = raw_symbol
        base_asset = buy_coin or symbol.replace(pay_coin, "")
    else:
        if not buy_coin:
            return jsonify({"error": "Target coin to buy is required (e.g. BAR)."}), 400
        if not pay_coin:
            pay_coin = "USDT"
        symbol = f"{buy_coin}{pay_coin}"
        base_asset = buy_coin

    try:
        quote_amount = float(data.get("amount", data.get("amount_usdt", 0)))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid amount to spend."}), 400

    if quote_amount <= 0:
        return jsonify({"error": f"Please enter an amount > 0 {pay_coin} to spend."}), 400

    try:
        client = get_client(testnet=testnet, api_key=api_key, api_secret=api_secret)
        order = place_market_buy_quote(client, symbol, quote_amount)
        _push_log("success", f"🛒 Spot Buy Executed: Spent {quote_amount} {pay_coin} to buy {symbol} | Order ID={order.get('orderId')}")
        
        # Fetch updated balances
        bal_info = client.get_asset_balance(asset=base_asset)
        free_qty = float(bal_info.get("free", 0)) if bal_info else 0.0

        quote_bal_info = client.get_asset_balance(asset=pay_coin)
        quote_free_qty = float(quote_bal_info.get("free", 0)) if quote_bal_info else 0.0

        return jsonify({
            "ok": True,
            "order": order,
            "symbol": symbol,
            "bought_asset": base_asset,
            "pay_asset": pay_coin,
            "new_balance": free_qty,
            "quote_balance": quote_free_qty,
        })
    except Exception as exc:
        _push_log("error", f"❌ Spot Buy Failed for {symbol}: {exc}")
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.route("/api/manual-sell", methods=["POST"])
def api_manual_sell():
    """Place an immediate manual MARKET SELL order on Binance spot (Sell All or Custom Quantity)."""
    global _monitor
    data = request.get_json(force=True)
    api_key = str(data.get("api_key", "")).strip()
    api_secret = str(data.get("api_secret", "")).strip()
    testnet = bool(data.get("testnet", True))
    symbol = str(data.get("symbol", "")).strip().upper()
    sell_mode = str(data.get("sell_mode", "all")).strip().lower()  # "all" or "quantity"
    quantity_type = str(data.get("quantity_type", "coin")).strip().lower()  # "coin" or "usdt"

    try:
        raw_qty = float(data.get("quantity", 0))
    except (ValueError, TypeError):
        raw_qty = 0.0

    if not symbol:
        return jsonify({"error": "Coin symbol is required."}), 400

    try:
        client = get_client(testnet=testnet, api_key=api_key, api_secret=api_secret)
        base_asset = symbol.replace("USDT", "")
        bal_info = client.get_asset_balance(asset=base_asset)
        total_free = float(bal_info.get("free", 0)) if bal_info else 0.0

        if total_free <= 0:
            return jsonify({"error": f"You have 0 {base_asset} available in your Spot Wallet to sell."}), 400

        if sell_mode == "all" or raw_qty <= 0:
            qty_to_sell = total_free
        else:
            if quantity_type == "usdt":
                cur_price = get_current_price(symbol, client=client)
                qty_to_sell = raw_qty / cur_price if cur_price > 0 else 0.0
            else:
                qty_to_sell = raw_qty

            if qty_to_sell > total_free:
                log.warning(f"Requested sell qty {qty_to_sell} exceeds available balance {total_free}. Adjusting to {total_free}.")
                qty_to_sell = total_free

        # Stop active monitor if running
        if _monitor and _monitor.is_running:
            _monitor.stop()
            _push_log("warning", f"⏹️ Active price monitor stopped due to manual market sell on {symbol}.")
            _push_status("idle")

        _push_log("warning", f"⚡ MANUAL SELL INITIATED: Placing MARKET SELL for {qty_to_sell} {symbol} ({sell_mode.upper()} mode) …")
        order = place_market_sell(client, symbol, qty_to_sell)

        usdt_proceeds = 0.0
        try:
            usdt_proceeds = float(order.get("cummulativeQuoteQty", 0.0))
        except (ValueError, TypeError):
            pass
        if usdt_proceeds <= 0:
            try:
                cur_p = get_current_price(symbol, client=client)
                usdt_proceeds = qty_to_sell * cur_p
            except Exception:
                pass

        _push_log(
            "success",
            f"⚡ MANUAL MARKET SELL EXECUTED! Sold {qty_to_sell} {symbol} for ${usdt_proceeds:.2f} USDT | Order ID={order.get('orderId')} | Status={order.get('status')}."
        )

        # Fetch new balance
        new_bal_info = client.get_asset_balance(asset=base_asset)
        new_free = float(new_bal_info.get("free", 0)) if new_bal_info else 0.0

        return jsonify({
            "ok": True,
            "order": order,
            "sold_symbol": symbol,
            "sold_quantity": qty_to_sell,
            "usdt_proceeds": usdt_proceeds,
            "new_balance": new_free,
        })
    except Exception as exc:
        _push_log("error", f"❌ Manual Market Sell Failed for {symbol}: {exc}")
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.route("/api/convert-all", methods=["POST"])
def api_convert_all():
    """Liquidate / Convert all non-zero spot coin holdings into a single target coin (e.g. USDT or BTC)."""
    global _monitor
    data = request.get_json(force=True)
    api_key = str(data.get("api_key", "")).strip()
    api_secret = str(data.get("api_secret", "")).strip()
    testnet = bool(data.get("testnet", True))
    target_asset = str(data.get("target_asset", "USDT")).strip().upper()

    if not target_asset:
        target_asset = "USDT"

    try:
        client = get_client(testnet=testnet, api_key=api_key, api_secret=api_secret)
        
        # Stop active monitor if running
        if _monitor and _monitor.is_running:
            _monitor.stop()
            _push_log("warning", "⏹️ Bot stopped due to Convert All action.")
            _push_status("idle")

        account_info = client.get_account()
        balances = account_info.get("balances", [])

        # Fetch exchange info once to lookup active pairs instantly
        exchange_info = client.get_exchange_info()
        tradable_symbols = {
            s["symbol"]: s for s in exchange_info.get("symbols", []) 
            if s.get("status") == "TRADING"
        }

        # Filter assets with free balance > 0 and not equal to target_asset
        sellable_assets = [
            b for b in balances 
            if float(b.get("free", 0)) > 0 and b["asset"].upper() != target_asset
        ]

        if not sellable_assets:
            return jsonify({"ok": True, "message": f"No other coins found to convert to {target_asset}.", "results": []})

        _push_log("warning", f"🧹 CONVERT ALL INITIATED: Converting {len(sellable_assets)} spot assets to {target_asset} …")

        results = []
        total_proceeds_usdt = 0.0

        for item in sellable_assets:
            asset = item["asset"].upper()
            free_qty = float(item["free"])

            # Skip non-standard or dummy testnet asset names
            if not asset.isalnum() or any(ord(c) > 127 for c in asset):
                log.info(f"Skipping non-standard asset: {asset}")
                results.append({"asset": asset, "status": "skipped", "reason": "Non-standard/Test coin"})
                continue

            # Determine trading pair
            direct_pair = f"{asset}{target_asset}"
            usdt_pair = f"{asset}USDT"

            pair_to_sell = ""
            if direct_pair in tradable_symbols:
                pair_to_sell = direct_pair
            elif usdt_pair in tradable_symbols:
                pair_to_sell = usdt_pair

            if not pair_to_sell:
                _push_log("warning", f"⚠️ Skipped {asset}: No active spot trading pair found on Binance.")
                results.append({"asset": asset, "status": "skipped", "reason": "No trading pair"})
                continue

            try:
                sell_res = place_market_sell(client, pair_to_sell, free_qty)
                proceeds = 0.0
                try:
                    proceeds = float(sell_res.get("cummulativeQuoteQty", 0.0))
                except (ValueError, TypeError):
                    pass

                quote_sym = pair_to_sell.replace(asset, "")
                _push_log("success", f"✅ Sold {free_qty} {asset} via {pair_to_sell} (Proceeds: {proceeds:.2f} {quote_sym})")
                results.append({
                    "asset": asset,
                    "status": "sold",
                    "pair": pair_to_sell,
                    "quantity": free_qty,
                    "proceeds": proceeds,
                })
                if pair_to_sell.endswith("USDT"):
                    total_proceeds_usdt += proceeds
            except Exception as e:
                _push_log("error", f"❌ Failed to sell {asset} ({pair_to_sell}): {e}")
                results.append({"asset": asset, "status": "error", "reason": str(e)})

        # If target_asset is NOT USDT and we have USDT proceeds (e.g. converting everything to BTC), buy target_asset with USDT
        if target_asset != "USDT" and total_proceeds_usdt >= 5.0:
            target_usdt_pair = f"{target_asset}USDT"
            if target_usdt_pair in tradable_symbols:
                try:
                    _push_log("info", f"🔄 Buying {target_asset} with accumulated ${total_proceeds_usdt:.2f} USDT proceeds …")
                    buy_res = place_market_buy_quote(client, target_usdt_pair, total_proceeds_usdt)
                    _push_log("success", f"🏆 Purchased {buy_res.get('executedQty')} {target_asset}!")
                except Exception as buy_e:
                    _push_log("error", f"❌ Failed to buy {target_asset} with USDT proceeds: {buy_e}")

        # Fetch updated target asset balance
        target_bal_info = client.get_asset_balance(asset=target_asset)
        final_target_bal = float(target_bal_info.get("free", 0.0)) if target_bal_info else 0.0

        _push_log("success", f"🎉 CONVERT ALL COMPLETE! Final {target_asset} Balance: {final_target_bal:,.4f} {target_asset}")

        return jsonify({
            "ok": True,
            "target_asset": target_asset,
            "final_balance": final_target_bal,
            "results": results,
        })
    except Exception as exc:
        _push_log("error", f"❌ Convert All Failed: {exc}")
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
            
            # Calculate USDT proceeds from the sell
            usdt_proceeds = 0.0
            try:
                usdt_proceeds = float(order.get("cummulativeQuoteQty", 0.0))
            except (ValueError, TypeError):
                pass
            if usdt_proceeds <= 0:
                try:
                    cur_p = get_current_price(sym, client=client)
                    usdt_proceeds = qty * cur_p
                except Exception:
                    usdt_proceeds = usdt_amount

            _push_log(
                "success",
                f"🎉 TARGET SECURED! Sold {qty} {sym} for ${usdt_proceeds:.2f} USDT | Order ID={order.get('orderId')} | Status={order.get('status')}.",
            )

            if auto_restart_on_trigger:
                _push_log("info", f"🔄 AUTO-RESTART: Re-buying {sym} using ${usdt_proceeds:.2f} USDT to start next profit cycle …")
                time.sleep(1.0)
                try:
                    spend_amount = usdt_proceeds if usdt_proceeds >= 5.0 else (usdt_amount if usdt_amount >= 5.0 else 50.0)
                    buy_order = place_market_buy_quote(client, sym, spend_amount)
                    
                    new_bought_qty = 0.0
                    try:
                        new_bought_qty = float(buy_order.get("executedQty", 0.0))
                    except (ValueError, TypeError):
                        pass
                    if new_bought_qty <= 0:
                        bal_info = client.get_asset_balance(asset=sym.replace("USDT", ""))
                        new_bought_qty = float(bal_info.get("free", 0.0)) if bal_info else qty

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
                        "quantity": new_bought_qty,
                        "usdt_amount": round(spend_amount, 2),
                    })

                    _push_log(
                        "success",
                        f"🚀 RE-BOUGHT {new_bought_qty} {sym} @ ${new_price:,.6f}! New Profit Target: ${new_target:,.6f} (+{target_percentage:.2f}%)"
                    )

                    start_monitoring_for_symbol(
                        current_sym=sym,
                        current_qty=new_bought_qty,
                        current_init_price=new_price,
                        current_target_price=new_target,
                    )
                except Exception as rebuy_err:
                    _push_log("error", f"❌ Failed to re-buy {sym} on auto-restart: {rebuy_err}")
                    _push_status("error")
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

            # ── Auto-Convert logic: Sell current coin & Buy Best 1H Gainer ──
            if auto_convert:
                # Check if exclusion list reached 3 coins and reset
                if len(_session_traded_symbols) >= 3:
                    _push_log(
                        "info",
                        f"🧹 Excluded coins list reached {len(_session_traded_symbols)} coins ({list(_session_traded_symbols)}). "
                        f"Resetting exclusion list to current symbol ({sym})!"
                    )
                    _session_traded_symbols.clear()
                    _session_traded_symbols.add(sym)

                _push_log("warning", f"🔄 Auto-Convert Enabled: Scanning for Best 1H Gainer on Binance (≥ +2% in last 1H, excluding {list(_session_traded_symbols)}) …")
                try:
                    top_gainer = find_top_gainer_1h(client=client, exclude_symbols=_session_traded_symbols)
                    top_sym = top_gainer["symbol"]
                    top_gain_1h_pct = top_gainer["gain_1h_pct"]
                    top_price = top_gainer["current_price"]
                    _session_traded_symbols.add(top_sym)

                    if len(_session_traded_symbols) >= 3:
                        _push_log(
                            "info",
                            f"🧹 Excluded list reached 3 coins after adding {top_sym}. "
                            f"Resetting list to only include current holding ({top_sym})."
                        )
                        _session_traded_symbols.clear()
                        _session_traded_symbols.add(top_sym)

                    _push_log("info", f"🏆 Best 1H Gainer: {top_sym} (+{top_gain_1h_pct}% in last 1H)")

                    _push_log("warning", f"💸 Executing Conversion: Selling {current_qty} {sym} → Buying {top_sym} …")
                    conversion = convert_coin_to_top_gainer(
                        client, sym, current_qty, top_sym, fallback_usdt_amount=usdt_amount
                    )

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
                        "top_gainer_1h_gain_pct": top_gain_1h_pct,
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
