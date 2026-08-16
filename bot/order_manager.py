"""
bot/order_manager.py
Places market sell and market buy orders on Binance.
Handles step-size / lot-size rounding and quoteOrderQty coin conversion.
"""

import math
import logging
from binance.client import Client
from bot.binance_client import get_symbol_info

log = logging.getLogger(__name__)


def _round_step_size(quantity: float, step_size: str) -> float:
    """Round quantity down to the nearest valid step size."""
    step = float(step_size)
    precision = int(round(-math.log(step, 10), 0))
    return round(math.floor(quantity / step) * step, precision)


def place_market_sell(
    client: Client,
    symbol: str,
    quantity: float,
) -> dict:
    """
    Place a MARKET SELL order.

    Args:
        client:   Authenticated Binance client.
        symbol:   Trading pair, e.g. 'BTCUSDT'.
        quantity: Amount of the base asset to sell.

    Returns:
        Order response dict from Binance.
    """
    symbol = symbol.upper()
    info = get_symbol_info(client, symbol)

    # Find LOT_SIZE filter to get step_size
    step_size = "1"
    for f in info.get("filters", []):
        if f["filterType"] == "LOT_SIZE":
            step_size = f["stepSize"]
            break

    qty = _round_step_size(quantity, step_size)
    if qty <= 0:
        raise ValueError(
            f"Rounded quantity is 0. Check that your amount ≥ min lot size for {symbol}."
        )

    log.info(f"[OrderManager] Placing MARKET SELL {qty} {symbol} …")
    order = client.order_market_sell(symbol=symbol, quantity=qty)
    log.info(f"[OrderManager] MARKET SELL order result: {order}")
    return order


def place_market_buy_quote(
    client: Client,
    symbol: str,
    quote_quantity: float,
) -> dict:
    """
    Place a MARKET BUY order spending a specified amount of quote asset (e.g. USDT).

    Args:
        client:         Authenticated Binance client.
        symbol:         Trading pair, e.g. 'SOLUSDT'.
        quote_quantity: Total amount of quote asset (USDT) to spend.

    Returns:
        Order response dict from Binance.
    """
    symbol = symbol.upper()
    info = get_symbol_info(client, symbol)

    # Check MIN_NOTIONAL filter
    min_notional = 5.0  # default 5 USDT min order
    for f in info.get("filters", []):
        if f["filterType"] in ("MIN_NOTIONAL", "NOTIONAL"):
            min_notional = float(f.get("minNotional", f.get("notional", 5.0)))
            break

    # Round quote quantity to 2 decimal places for USDT
    quote_qty = round(quote_quantity, 2)
    if quote_qty < min_notional:
        raise ValueError(
            f"Quote order amount (${quote_qty:.2f}) is below minimum notional filter (${min_notional:.2f}) for {symbol}."
        )

    log.info(f"[OrderManager] Placing MARKET BUY {symbol} spending ${quote_qty:.2f} USDT …")
    order = client.order_market_buy(symbol=symbol, quoteOrderQty=quote_qty)
    log.info(f"[OrderManager] MARKET BUY order result: {order}")
    return order


def convert_coin_to_top_gainer(
    client: Client,
    old_symbol: str,
    sell_quantity: float,
    top_gainer_symbol: str,
) -> dict:
    """
    Step 1: Sell original asset (old_symbol).
    Step 2: Take USDT proceeds and buy top_gainer_symbol (MARKET BUY via quoteOrderQty).

    Returns summary dict containing details of both trades.
    """
    old_symbol = old_symbol.upper()
    top_gainer_symbol = top_gainer_symbol.upper()

    log.info(f"[OrderManager] 🔄 Starting Coin Conversion: Selling {sell_quantity} {old_symbol} -> Buying {top_gainer_symbol}")

    # 1. Execute MARKET SELL on old symbol
    sell_order = place_market_sell(client, old_symbol, sell_quantity)

    # Calculate net USDT proceeds
    usdt_proceeds = 0.0
    try:
        usdt_proceeds = float(sell_order.get("cummulativeQuoteQty", 0.0))
    except (ValueError, TypeError):
        pass

    if usdt_proceeds <= 0:
        # Fallback: estimate using current ticker price if cummulativeQuoteQty not returned
        ticker = client.get_symbol_ticker(symbol=old_symbol)
        price = float(ticker.get("price", 0))
        usdt_proceeds = sell_quantity * price

    log.info(f"[OrderManager] 💵 Market sell proceeds: ${usdt_proceeds:.2f} USDT")

    # 2. Execute MARKET BUY on top gainer symbol using USDT proceeds
    buy_order = place_market_buy_quote(client, top_gainer_symbol, usdt_proceeds)

    bought_qty = 0.0
    try:
        bought_qty = float(buy_order.get("executedQty", 0.0))
    except (ValueError, TypeError):
        pass

    summary = {
        "old_symbol": old_symbol,
        "sold_quantity": sell_quantity,
        "sell_order_id": sell_order.get("orderId"),
        "usdt_proceeds": round(usdt_proceeds, 2),
        "new_symbol": top_gainer_symbol,
        "bought_quantity": bought_qty,
        "buy_order_id": buy_order.get("orderId"),
        "sell_order": sell_order,
        "buy_order": buy_order,
    }

    log.info(
        f"[OrderManager] ✅ Conversion Complete! "
        f"Sold {sell_quantity} {old_symbol} for ${usdt_proceeds:.2f} USDT -> Bought {bought_qty} {top_gainer_symbol}"
    )

    return summary
