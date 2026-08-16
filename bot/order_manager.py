"""
bot/order_manager.py
Places market sell and market buy orders on Binance.
Robustly handles LOT_SIZE, MARKET_LOT_SIZE (minQty, maxQty, stepSize),
NOTIONAL/MIN_NOTIONAL filters, and automatic chunking for large market orders.
"""

import math
import logging
from decimal import Decimal
from binance.client import Client
from bot.binance_client import get_symbol_info

log = logging.getLogger(__name__)


def _get_filter(info: dict, filter_type: str) -> dict:
    """Find a specific filter dictionary from Binance symbol exchange info."""
    for f in info.get("filters", []):
        if f.get("filterType") == filter_type:
            return f
    return {}


def _format_quantity(val: Decimal, step: Decimal) -> float:
    """Return cleanly rounded float matching Binance stepSize precision."""
    if step == step.to_integral():
        return float(int(val))
    step_str = f"{step:f}".rstrip("0")
    precision = len(step_str.split(".")[1]) if "." in step_str else 0
    return float(f"{val:.{precision}f}")


def place_market_sell(
    client: Client,
    symbol: str,
    quantity: float,
) -> dict:
    """
    Place a MARKET SELL order.
    Automatically handles LOT_SIZE and MARKET_LOT_SIZE filters.
    If the requested quantity exceeds the single market order maxQty,
    it automatically splits the order into valid market order chunks.

    Args:
        client:   Authenticated Binance client.
        symbol:   Trading pair, e.g. 'PIVXUSDT'.
        quantity: Amount of the base asset to sell.

    Returns:
        Order response dict (or aggregated result for chunked orders).
    """
    symbol = symbol.upper()
    info = get_symbol_info(client, symbol)

    lot_filter = _get_filter(info, "LOT_SIZE")
    market_lot_filter = _get_filter(info, "MARKET_LOT_SIZE")

    # Step size: prefer LOT_SIZE stepSize, fallback to MARKET_LOT_SIZE
    step_size_str = lot_filter.get("stepSize") or "1"
    if float(step_size_str) == 0 and market_lot_filter.get("stepSize"):
        step_size_str = market_lot_filter.get("stepSize", "1")
    step = Decimal(str(float(step_size_str))) if float(step_size_str) > 0 else Decimal("1")

    # Minimum Quantity
    min_qty = Decimal(str(lot_filter.get("minQty", "0")))
    if market_lot_filter.get("minQty") and Decimal(str(market_lot_filter["minQty"])) > 0:
        min_qty = max(min_qty, Decimal(str(market_lot_filter["minQty"])))

    # Maximum Market Order Quantity (crucial for MARKET_LOT_SIZE filter!)
    max_market_qty = Decimal("0")
    if market_lot_filter.get("maxQty") and float(market_lot_filter["maxQty"]) > 0:
        max_market_qty = Decimal(str(market_lot_filter["maxQty"]))
    elif lot_filter.get("maxQty") and float(lot_filter["maxQty"]) > 0:
        max_market_qty = Decimal(str(lot_filter["maxQty"]))

    total_req = Decimal(str(quantity))
    # Round down to nearest valid step
    total_to_sell = total_req - (total_req % step)

    if total_to_sell <= 0 or total_to_sell < min_qty:
        raise ValueError(
            f"Quantity ({total_to_sell}) is below minimum lot size ({min_qty}) for {symbol}."
        )

    # Chunk into orders <= max_market_qty
    chunks: list[Decimal] = []
    rem = total_to_sell
    while rem > 0:
        chunk = rem if max_market_qty <= 0 else min(rem, max_market_qty)
        chunk = chunk - (chunk % step)
        if chunk <= 0:
            break
        chunks.append(chunk)
        rem -= chunk

    if not chunks:
        raise ValueError(f"No valid sell quantity could be computed for {symbol}.")

    log.info(
        f"[OrderManager] Placing MARKET SELL for {total_to_sell} {symbol} "
        f"in {len(chunks)} order(s) (Max chunk: {max_market_qty}) …"
    )

    orders = []
    total_proceeds = 0.0
    total_executed_qty = 0.0

    for i, chk in enumerate(chunks, start=1):
        formatted_qty = _format_quantity(chk, step)
        if len(chunks) > 1:
            log.info(f"[OrderManager] [Chunk {i}/{len(chunks)}] Selling {formatted_qty} {symbol} …")
        
        order = client.order_market_sell(symbol=symbol, quantity=formatted_qty)
        orders.append(order)

        try:
            total_proceeds += float(order.get("cummulativeQuoteQty", 0.0))
            total_executed_qty += float(order.get("executedQty", 0.0))
        except (ValueError, TypeError):
            pass

    # Build primary result dict
    primary_order = orders[0].copy()
    primary_order["cummulativeQuoteQty"] = f"{total_proceeds:.8f}"
    primary_order["executedQty"] = f"{total_executed_qty:.8f}"
    primary_order["sub_orders"] = orders
    if len(orders) > 1:
        primary_order["orderId"] = f"{orders[0].get('orderId')} (+{len(orders)-1} chunks)"

    log.info(
        f"[OrderManager] MARKET SELL complete. Total executed: {total_executed_qty} {symbol}, "
        f"Total proceeds: ${total_proceeds:.2f} USDT"
    )
    return primary_order


def place_market_buy_quote(
    client: Client,
    symbol: str,
    quote_quantity: float,
) -> dict:
    """
    Place a MARKET BUY order spending a specified amount of quote asset (e.g. USDT).
    Handles MIN_NOTIONAL and NOTIONAL filters.

    Args:
        client:         Authenticated Binance client.
        symbol:         Trading pair, e.g. 'PORTALUSDT'.
        quote_quantity: Total amount of quote asset (USDT) to spend.

    Returns:
        Order response dict from Binance.
    """
    symbol = symbol.upper()
    info = get_symbol_info(client, symbol)

    # Check NOTIONAL / MIN_NOTIONAL filter
    notional_filter = _get_filter(info, "NOTIONAL") or _get_filter(info, "MIN_NOTIONAL")
    min_notional = float(notional_filter.get("minNotional", notional_filter.get("notional", 5.0)))
    max_notional = float(notional_filter.get("maxNotional", 0.0))
    apply_max_to_market = notional_filter.get("applyMaxToMarket", False)

    quote_qty = round(float(quote_quantity), 2)
    if quote_qty < min_notional:
        raise ValueError(
            f"Quote order amount (${quote_qty:.2f}) is below minimum notional filter (${min_notional:.2f}) for {symbol}."
        )

    # Chunk if quote_qty > max_notional and applyMaxToMarket is True
    chunks: list[float] = []
    if apply_max_to_market and max_notional > 0 and quote_qty > max_notional:
        rem = quote_qty
        while rem > 0:
            c = min(rem, max_notional)
            c = round(c, 2)
            if c <= 0:
                break
            chunks.append(c)
            rem = round(rem - c, 2)
    else:
        chunks = [quote_qty]

    orders = []
    total_bought_qty = 0.0
    total_spent_usdt = 0.0

    for i, chk in enumerate(chunks, start=1):
        if len(chunks) > 1:
            log.info(f"[OrderManager] [Buy Chunk {i}/{len(chunks)}] Buying {symbol} with ${chk:.2f} USDT …")
        order = client.order_market_buy(symbol=symbol, quoteOrderQty=f"{chk:.2f}")
        orders.append(order)
        try:
            total_bought_qty += float(order.get("executedQty", 0.0))
            total_spent_usdt += float(order.get("cummulativeQuoteQty", 0.0))
        except (ValueError, TypeError):
            pass

    primary_order = orders[0].copy()
    primary_order["executedQty"] = f"{total_bought_qty:.8f}"
    primary_order["cummulativeQuoteQty"] = f"{total_spent_usdt:.8f}"
    primary_order["sub_orders"] = orders
    if len(orders) > 1:
        primary_order["orderId"] = f"{orders[0].get('orderId')} (+{len(orders)-1} chunks)"

    log.info(
        f"[OrderManager] MARKET BUY complete. Total bought: {total_bought_qty} {symbol} "
        f"for ${total_spent_usdt:.2f} USDT"
    )
    return primary_order


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

    log.info(
        f"[OrderManager] 🔄 Starting Coin Conversion: "
        f"Selling {sell_quantity} {old_symbol} -> Buying {top_gainer_symbol}"
    )

    # 1. Execute MARKET SELL on old symbol (automatically handles MARKET_LOT_SIZE & chunking)
    sell_order = place_market_sell(client, old_symbol, sell_quantity)

    # Calculate net USDT proceeds
    usdt_proceeds = 0.0
    try:
        usdt_proceeds = float(sell_order.get("cummulativeQuoteQty", 0.0))
    except (ValueError, TypeError):
        pass

    if usdt_proceeds <= 0:
        # Fallback: estimate using current ticker price
        ticker = client.get_symbol_ticker(symbol=old_symbol)
        price = float(ticker.get("price", 0))
        sold_qty = float(sell_order.get("executedQty", sell_quantity))
        usdt_proceeds = sold_qty * price

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
        "sold_quantity": float(sell_order.get("executedQty", sell_quantity)),
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
        f"Sold {summary['sold_quantity']} {old_symbol} for ${usdt_proceeds:.2f} USDT -> "
        f"Bought {bought_qty} {top_gainer_symbol}"
    )

    return summary
