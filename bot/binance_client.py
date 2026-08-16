"""
bot/binance_client.py
Thin wrapper around python-binance Client that supports
both Testnet and Live modes transparently.
Price fetching uses the LIVE Binance REST API (api.binance.com)
via requests, which is fully compatible with eventlet.
"""

import requests as http_requests
from binance.client import Client
from config.settings import settings

# Live Binance REST endpoint for public price data
_LIVE_TICKER_URL = "https://api.binance.com/api/v3/ticker/price"


def get_client(testnet: bool = True) -> Client:
    """
    Return an authenticated Binance Client.

    Args:
        testnet: If True, use Testnet credentials and endpoint.
                 If False, use Live credentials.
    Returns:
        binance.client.Client
    """
    try:
        if testnet:
            client = Client(
                api_key=settings.TESTNET_API_KEY,
                api_secret=settings.TESTNET_API_SECRET,
                testnet=True,
            )
        else:
            client = Client(
                api_key=settings.LIVE_API_KEY,
                api_secret=settings.LIVE_API_SECRET,
            )
        return client
    except Exception as err:
        err_msg = str(err)
        if "NameResolutionError" in err_msg or "Failed to resolve" in err_msg or "11002" in err_msg:
            raise ConnectionError(
                f"Failed to connect to Binance ({'Testnet' if testnet else 'Live'}) due to DNS lookup failure.\n"
                "Suggestions:\n"
                "  1. Flush your DNS cache (ipconfig /flushdns) or change your DNS server to Google (8.8.8.8) or Cloudflare (1.1.1.1).\n"
                f"Original error: {err}"
            ) from err
        raise err


def get_symbol_info(client: Client, symbol: str) -> dict:
    """Return exchange info for a given symbol (filters, precision, etc.)."""
    info = client.get_symbol_info(symbol.upper())
    if info is None:
        raise ValueError(f"Symbol '{symbol}' not found on Binance.")
    return info


def get_current_price(symbol: str, client: Client | None = None) -> float:
    """
    Fetch the latest price for a symbol.
    Uses Binance Client if provided, otherwise fetches from the public Binance REST API.
    """
    symbol = symbol.strip().upper()
    if client:
        ticker = client.get_symbol_ticker(symbol=symbol)
        return float(ticker["price"])

    resp = http_requests.get(
        _LIVE_TICKER_URL,
        params={"symbol": symbol},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    return float(data["price"])
