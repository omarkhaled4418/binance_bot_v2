"""
bot/strategy.py
Market scanner and strategy helper.
Finds the top gaining coin over the last 4 hours on Binance USDT spot market.
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


def find_top_gainer_4h(
    client: Client | None = None,
    exclude_symbols: str | set[str] | list[str] = "",
    min_volume_usdt: float = 500_000.0,
    top_candidates_count: int = 30,
) -> dict:
    """
    Find the coin with the highest percentage price gain over the last 4 hours.
    Skips any symbols in exclude_symbols to prevent re-buying the current or recently traded coin.

    Args:
        client:               Optional authenticated Binance client.
        exclude_symbols:      Symbol or collection of symbols to exclude.
        min_volume_usdt:      Minimum 24h quote volume in USDT to ensure liquidity.
        top_candidates_count: Number of top volume pairs to scan 4h klines for.

    Returns:
        dict: {
            "symbol": str,
            "gain_4h_pct": float,
            "current_price": float,
            "open_4h_price": float,
            "quote_volume_24h": float
        }
    """
    if isinstance(exclude_symbols, str):
        excluded_set = {exclude_symbols.strip().upper()} if exclude_symbols else set()
    else:
        excluded_set = {s.strip().upper() for s in exclude_symbols if s}

    log.info(f"[Strategy] Scanning Binance market for Top 4H Gainer (excluding {excluded_set}) …")

    # 1. Fetch 24h tickers to filter liquid USDT pairs
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
        try:
            quote_vol = float(t.get("quoteVolume", 0))
            if quote_vol >= min_volume_usdt:
                candidates.append({
                    "symbol": sym,
                    "quote_volume_24h": quote_vol,
                })
        except (ValueError, TypeError):
            continue

    if not candidates:
        raise ValueError("No eligible USDT trading pairs found matching volume criteria.")

    # Sort candidates by 24h volume descending to check top liquid coins
    candidates.sort(key=lambda x: x["quote_volume_24h"], reverse=True)
    top_candidates = candidates[:top_candidates_count]

    # 2. Query 1h klines (limit=5) to calculate exact 4h price gain
    gainer_results = []
    for c in top_candidates:
        sym = c["symbol"]
        try:
            k_resp = http_requests.get(
                _KLINES_URL,
                params={"symbol": sym, "interval": "1h", "limit": 5},
                timeout=5,
            )
            k_resp.raise_for_status()
            klines = k_resp.json()
            if len(klines) >= 5:
                open_4h_ago = float(klines[-5][1])   # Open price of candle 4h ago
                current_close = float(klines[-1][4]) # Current price
                if open_4h_ago > 0:
                    gain_4h_pct = ((current_close - open_4h_ago) / open_4h_ago) * 100.0
                    gainer_results.append({
                        "symbol": sym,
                        "gain_4h_pct": round(gain_4h_pct, 2),
                        "current_price": current_close,
                        "open_4h_price": open_4h_ago,
                        "quote_volume_24h": c["quote_volume_24h"],
                    })
        except Exception as exc:
            log.warning(f"[Strategy] Could not fetch 4H klines for {sym}: {exc}")
            continue

    if not gainer_results:
        raise ValueError("Failed to calculate 4H gains for market candidates.")

    # Sort candidates by 4h gain percentage descending
    gainer_results.sort(key=lambda x: x["gain_4h_pct"], reverse=True)

    # Pick the top gainer that is NOT in the excluded set
    top_gainer = None
    for res in gainer_results:
        if res["symbol"] not in excluded_set:
            top_gainer = res
            break

    if not top_gainer:
        top_gainer = gainer_results[0]  # Fallback to #1 in list if all excluded

    log.info(
        f"[Strategy] 🏆 Top 4H Gainer Found: {top_gainer['symbol']} "
        f"(+{top_gainer['gain_4h_pct']}% 4H gain, Current: ${top_gainer['current_price']})"
    )

    return top_gainer
