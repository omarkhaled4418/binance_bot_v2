"""
run.py – Entry point for the Binance Sell Bot dashboard.

Usage:
    python run.py

The web dashboard will be available at http://localhost:5000
"""

import sys
import os
import logging

# Make sure sub-packages are importable from the project root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.settings import settings
from dashboard.app import app, socketio

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# Fix python-binance compatibility with websockets>=14.0
try:
    from binance.streams import ReconnectingWebsocket
    _orig_aexit = ReconnectingWebsocket.__aexit__
    async def _safe_aexit(self, exc_type, exc_val, exc_tb):
        if self.ws and not hasattr(self.ws, "fail_connection"):
            self.ws.fail_connection = lambda *a, **k: None
        return await _orig_aexit(self, exc_type, exc_val, exc_tb)
    ReconnectingWebsocket.__aexit__ = _safe_aexit
except Exception:
    pass

if __name__ == "__main__":
    print("\n" + "=" * 55)
    print("  Binance Sell Bot - Dashboard")
    print(f"  http://localhost:{settings.FLASK_PORT}")
    print("  Copy .env.example -> .env and add your API keys")
    print("=" * 55 + "\n")

    socketio.run(
        app,
        host=settings.FLASK_HOST,
        port=settings.FLASK_PORT,
        debug=False,
        use_reloader=False,
        allow_unsafe_werkzeug=True,
    )
