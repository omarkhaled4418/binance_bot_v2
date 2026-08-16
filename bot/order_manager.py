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

    # Check available base asset balance in account
    base_asset = info.get("baseAsset", symbol.replace("USDT", ""))
    try:
        balance_info = client.get_asset_balance(asset=base_asset)
        if balance_info:
            free_bal = float(balance_info.get("free", 0))
            if free_bal <= 0:
                raise ValueError(
                    f"Insufficient balance: You have 0 {base_asset} in your Binance account. "
                    f"Please buy {base_asset} first before monitoring a sell order."
                )
            if free_bal < qty:
                log.warning(
                    f"[OrderManager] Requested amount ({qty} {base_asset}) exceeds available balance ({free_bal} {base_asset}). "
                    f"Auto-adjusting sell order to full available balance: {free_bal} {base_asset}."
                )
                qty = _round_step_size(free_bal, step_size)
                if qty <= 0:
                    raise ValueError(
                        f"Available balance ({free_bal} {base_asset}) is smaller than the minimum lot step ({step_size})."
                    )
    except Exception as exc:
        if "Insufficient balance" in str(exc) or "smaller than the minimum" in str(exc):
            raise exc
        log.warning(f"[OrderManager] Could not verify balance for {base_asset}: {exc}")

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
    Place a MARKET BUY order spending a specified amount of quote asset (e.g. USDT, BNB, BTC).

    Args:
        client:         Authenticated Binance client.
        symbol:         Trading pair, e.g. 'BARUSDT' or 'BARBNB'.
        quote_quantity: Total amount of quote asset to spend.

    Returns:
        Order response dict from Binance.
    """
    symbol = symbol.upper()
    info = get_symbol_info(client, symbol)
    quote_asset = info.get("quoteAsset", "USDT")
    quote_precision = int(info.get("quoteAssetPrecision", 2))

    # Check available balance of the quote asset (the coin being spent)
    try:
        quote_bal_info = client.get_asset_balance(asset=quote_asset)
        if quote_bal_info:
            free_quote_bal = float(quote_bal_info.get("free", 0))
            if free_quote_bal < quote_quantity:
                if free_quote_bal <= 0:
                    raise ValueError(
                        f"Insufficient {quote_asset} balance: You have 0 {quote_asset} in your Spot Wallet."
                    )
                log.warning(
                    f"[OrderManager] Requested {quote_quantity} {quote_asset} exceeds available balance ({free_quote_bal} {quote_asset}). "
                    f"Auto-adjusting buy amount to available balance: {free_quote_bal} {quote_asset}."
                )
                quote_quantity = free_quote_bal
    except Exception as exc:
        if "Insufficient" in str(exc):
            raise exc
        log.warning(f"[OrderManager] Could not verify quote balance for {quote_asset}: {exc}")

    # Check MIN_NOTIONAL filter
    min_notional = 5.0  # default min order value
    for f in info.get("filters", []):
        if f["filterType"] in ("MIN_NOTIONAL", "NOTIONAL"):
            min_notional = float(f.get("minNotional", f.get("notional", 5.0)))
            break

    quote_qty = round(quote_quantity, min(quote_precision, 8))
    if quote_qty < min_notional:
        raise ValueError(
            f"Quote order amount ({quote_qty} {quote_asset}) is below minimum notional filter ({min_notional} {quote_asset}) for {symbol}."
        )

    log.info(f"[OrderManager] Placing MARKET BUY {symbol} spending {quote_qty} {quote_asset} …")
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
