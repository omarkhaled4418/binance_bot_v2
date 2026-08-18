"""
bot/strategy.py
Market scanner and strategy helper.
Finds the top gaining coin over the last 1 hour on Binance USDT spot market.
"""

import logging
import requests as http_requests
from binance.client import Client

log = logging.getLogger(__name__)

# Base Binance REST endpoint for public market data scan
_TICKER_24HR_URL = "https://api.binance.com/api/v3/ticker/24hr"
_KLINES_URL = "https://api.binance.com/api/v3/klines"

# List of stablecoins / fiat assets to exclude from top gainers scan
_EXCLUDED_PAIRS = {
    "USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "BUSDUSDT", "DAIUSDT",
    "EURUSDT", "GBPUSDT", "WBTCUSDT", "AEURUSDT", "USDEUSDT"
}


def find_top_gainer_1h(
    client: Client | None = None,
    exclude_symbols: str | set[str] | list[str] = "",
    min_volume_usdt: float = 250_000.0,
    top_candidates_count: int = 50,
) -> dict:
    """
    Find the coin with the highest percentage price gain over the last 1 hour.
    No minimum threshold — simply picks the best 1H gainer available.

    Args:
        client:               Optional authenticated Binance client.
        exclude_symbols:      Symbol or collection of symbols to exclude.
        min_volume_usdt:      Minimum 24h quote volume in USDT to ensure liquidity.
        top_candidates_count: Number of candidates to scan klines for.

    Returns:
        dict: {
            "symbol": str,
            "gain_1h_pct": float,
            "current_price": float,
            "open_1h_price": float,
            "quote_volume_24h": float
        }
    """
    if isinstance(exclude_symbols, str):
        excluded_set = {exclude_symbols.strip().upper()} if exclude_symbols else set()
    else:
        excluded_set = {s.strip().upper() for s in exclude_symbols if s}

    log.info(
        f"[Strategy] Scanning Binance market for Best 1H Gainer (excluding {excluded_set}) …"
    )

    # 1. Fetch tradable symbols on the target client exchange (e.g. Testnet vs Live)
    supported_symbols = set()
    if client:
        try:
            ex_info = client.get_exchange_info()
            supported_symbols = {
                s["symbol"] for s in ex_info.get("symbols", [])
                if s.get("status") == "TRADING"
            }
            log.info(f"[Strategy] Client exchange supports {len(supported_symbols)} trading pairs.")
        except Exception as e:
            log.warning(f"[Strategy] Could not fetch client exchange info: {e}")

    # 2. Fetch 24h tickers to filter liquid USDT pairs
    try:
        resp = http_requests.get(_TICKER_24HR_URL, timeout=10)
        resp.raise_for_status()
        tickers = resp.json()
    except Exception as exc:
        log.error(f"[Strategy] Failed to fetch 24h tickers: {exc}")
        raise RuntimeError(f"Failed to scan Binance market tickers: {exc}") from exc

    candidates = []
    for t in tickers:
        sym = t.get("symbol", "")
        if not sym.endswith("USDT"):
            continue
        if sym in _EXCLUDED_PAIRS or sym in excluded_set:
            continue
        # If client exchange symbols were loaded, ensure symbol exists on target exchange
        if supported_symbols and sym not in supported_symbols:
            continue
        try:
            quote_vol = float(t.get("quoteVolume", 0))
            price_change_pct = float(t.get("priceChangePercent", 0))
            if quote_vol >= min_volume_usdt and price_change_pct > 0:
                candidates.append({
                    "symbol": sym,
                    "quote_volume_24h": quote_vol,
                    "price_change_24h": price_change_pct,
                })
        except (ValueError, TypeError):
            continue

    if not candidates:
        # If strict volume filter yielded 0 pairs (especially on testnet), relax volume requirement
        for t in tickers:
            sym = t.get("symbol", "")
            if not sym.endswith("USDT") or sym in _EXCLUDED_PAIRS or sym in excluded_set:
                continue
            if supported_symbols and sym not in supported_symbols:
                continue
            price_change_pct = float(t.get("priceChangePercent", 0))
            candidates.append({
                "symbol": sym,
                "quote_volume_24h": float(t.get("quoteVolume", 0)),
                "price_change_24h": price_change_pct,
            })

    if not candidates:
        raise ValueError("No eligible USDT trading pairs found matching criteria on target exchange.")

    # Sort candidates by 24h price change and volume (pre-filter for kline scan)
    candidates.sort(key=lambda x: (x["price_change_24h"], x["quote_volume_24h"]), reverse=True)
    top_candidates = candidates[:top_candidates_count]

    # 3. Query 1h klines (limit=3) to calculate exact 1h price gain
    gainer_results = []
    for c in top_candidates:
        sym = c["symbol"]
        try:
            k_resp = http_requests.get(
                _KLINES_URL,
                params={"symbol": sym, "interval": "1h", "limit": 3},
                timeout=5,
            )
            k_resp.raise_for_status()
            klines = k_resp.json()
            if len(klines) >= 2:
                open_1h_ago = float(klines[-2][1])   # Open price of the completed 1h candle
                current_close = float(klines[-1][4]) # Current close price

                if open_1h_ago > 0:
                    gain_1h_pct = ((current_close - open_1h_ago) / open_1h_ago) * 100.0

                    gainer_results.append({
                        "symbol": sym,
                        "gain_1h_pct": round(gain_1h_pct, 2),
                        "current_price": current_close,
                        "open_1h_price": open_1h_ago,
                        "quote_volume_24h": c["quote_volume_24h"],
                    })
        except Exception as exc:
            log.warning(f"[Strategy] Could not fetch klines for {sym}: {exc}")
            continue

    if not gainer_results:
        raise ValueError("No suitable gainers found on Binance USDT market.")

    # Sort by 1H gain (primary ranking)
    gainer_results.sort(key=lambda x: x["gain_1h_pct"], reverse=True)

    # Pick the top candidate not in excluded_set
    top_gainer = None
    for res in gainer_results:
        if res["symbol"] not in excluded_set:
            top_gainer = res
            break

    if not top_gainer:
        top_gainer = gainer_results[0]

    log.info(
        f"[Strategy] 🏆 Best 1H Gainer Selected: {top_gainer['symbol']} "
        f"(1H Gain: +{top_gainer['gain_1h_pct']}%, Price: ${top_gainer['current_price']})"
    )

    return top_gainer


# Backward-compatible alias
find_top_gainer_4h = find_top_gainer_1h
