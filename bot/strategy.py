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
    min_volume_usdt: float = 250_000.0,
    min_1h_gain_pct: float = 2.0,
    top_candidates_count: int = 50,
) -> dict:
    """
    Find the coin with the highest percentage price gain over the last 4 hours,
    requiring AT LEAST +2% price increase in the last 1 hour.
    Skips any symbols that haven't increased by at least 2% in the last hour,
    and skips any symbols in exclude_symbols.

    Args:
        client:               Optional authenticated Binance client.
        exclude_symbols:      Symbol or collection of symbols to exclude.
        min_volume_usdt:      Minimum 24h quote volume in USDT to ensure liquidity.
        min_1h_gain_pct:      Minimum required price increase in the last 1 hour (default: 2.0%).
        top_candidates_count: Number of candidates to scan klines for.

    Returns:
        dict: {
            "symbol": str,
            "gain_4h_pct": float,
            "gain_1h_pct": float,
            "current_price": float,
            "open_4h_price": float,
            "quote_volume_24h": float
        }
    """
    if isinstance(exclude_symbols, str):
        excluded_set = {exclude_symbols.strip().upper()} if exclude_symbols else set()
    else:
        excluded_set = {s.strip().upper() for s in exclude_symbols if s}

    log.info(
        f"[Strategy] Scanning Binance market for Top Gainer (Minimum 1H Gain ≥ +{min_1h_gain_pct}%, excluding {excluded_set}) …"
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

    # Sort candidates by 24h price change and volume
    candidates.sort(key=lambda x: (x["price_change_24h"], x["quote_volume_24h"]), reverse=True)
    top_candidates = candidates[:top_candidates_count]

    # 2. Query 1h klines (limit=6) to calculate exact 4h and 1h price gains
    gainer_results = []
    for c in top_candidates:
        sym = c["symbol"]
        try:
            k_resp = http_requests.get(
                _KLINES_URL,
                params={"symbol": sym, "interval": "1h", "limit": 6},
                timeout=5,
            )
            k_resp.raise_for_status()
            klines = k_resp.json()
            if len(klines) >= 5:
                open_4h_ago = float(klines[-5][1])   # Open price 4h ago
                open_1h_ago = float(klines[-2][1])   # Open price 1h ago
                current_close = float(klines[-1][4]) # Current price

                if open_4h_ago > 0 and open_1h_ago > 0:
                    gain_4h_pct = ((current_close - open_4h_ago) / open_4h_ago) * 100.0
                    gain_1h_pct = ((current_close - open_1h_ago) / open_1h_ago) * 100.0

                    # Check 1-hour minimum gain filter
                    if gain_1h_pct < min_1h_gain_pct:
                        log.debug(
                            f"[Strategy] Skipping {sym}: 1H gain (+{gain_1h_pct:.2f}%) < required +{min_1h_gain_pct}%"
                        )
                        continue

                    gainer_results.append({
                        "symbol": sym,
                        "gain_4h_pct": round(gain_4h_pct, 2),
                        "gain_1h_pct": round(gain_1h_pct, 2),
                        "current_price": current_close,
                        "open_4h_price": open_4h_ago,
                        "quote_volume_24h": c["quote_volume_24h"],
                    })
        except Exception as exc:
            log.warning(f"[Strategy] Could not fetch klines for {sym}: {exc}")
            continue

    if not gainer_results:
        log.warning(
            f"[Strategy] No coins met the strict +{min_1h_gain_pct}% 1H gain threshold. Falling back to highest 1H gainer above 0% …"
        )
        # Fallback: find best positive 1h gainer if none met +2%
        for c in top_candidates[:20]:
            sym = c["symbol"]
            try:
                k_resp = http_requests.get(
                    _KLINES_URL,
                    params={"symbol": sym, "interval": "1h", "limit": 6},
                    timeout=5,
                )
                k_resp.raise_for_status()
                klines = k_resp.json()
                if len(klines) >= 5:
                    open_4h_ago = float(klines[-5][1])
                    open_1h_ago = float(klines[-2][1])
                    current_close = float(klines[-1][4])
                    if open_4h_ago > 0 and open_1h_ago > 0:
                        gain_4h_pct = ((current_close - open_4h_ago) / open_4h_ago) * 100.0
                        gain_1h_pct = ((current_close - open_1h_ago) / open_1h_ago) * 100.0
                        gainer_results.append({
                            "symbol": sym,
                            "gain_4h_pct": round(gain_4h_pct, 2),
                            "gain_1h_pct": round(gain_1h_pct, 2),
                            "current_price": current_close,
                            "open_4h_price": open_4h_ago,
                            "quote_volume_24h": c["quote_volume_24h"],
                        })
            except Exception:
                continue

    if not gainer_results:
        raise ValueError(f"No suitable gainers found on Binance USDT market.")

    # Sort candidates by 1h gain and 4h gain
    gainer_results.sort(key=lambda x: (x["gain_1h_pct"], x["gain_4h_pct"]), reverse=True)

    # Pick the top candidate not in excluded_set
    top_gainer = None
    for res in gainer_results:
        if res["symbol"] not in excluded_set:
            top_gainer = res
            break

    if not top_gainer:
        top_gainer = gainer_results[0]

    log.info(
        f"[Strategy] 🏆 Top Momentum Coin Selected: {top_gainer['symbol']} "
        f"(1H Gain: +{top_gainer['gain_1h_pct']}%, 4H Gain: +{top_gainer['gain_4h_pct']}%, Price: ${top_gainer['current_price']})"
    )

    return top_gainer
