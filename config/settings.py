"""
config/settings.py
Loads environment variables and exposes a single Settings object.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # ── Live credentials ──
    LIVE_API_KEY: str = os.getenv("BINANCE_API_KEY", "")
    LIVE_API_SECRET: str = os.getenv("BINANCE_API_SECRET", "")

    # ── Testnet credentials ──
    TESTNET_API_KEY: str = os.getenv("BINANCE_TESTNET_API_KEY", "")
    TESTNET_API_SECRET: str = os.getenv("BINANCE_TESTNET_API_SECRET", "")

    # ── Flask ──
    FLASK_SECRET_KEY: str = os.getenv("FLASK_SECRET_KEY", "dev-secret-key")
    FLASK_HOST: str = os.getenv("FLASK_HOST", "0.0.0.0")
    FLASK_PORT: int = int(os.getenv("PORT", os.getenv("FLASK_PORT", "5000")))

    # ── n8n Webhook / Price Drop Settings ──
    N8N_WEBHOOK_URL: str = os.getenv("N8N_WEBHOOK_URL", "")
    DEFAULT_DROP_PERCENTAGE: float = float(os.getenv("DEFAULT_DROP_PERCENTAGE", "5.0"))
    AUTO_CONVERT_ON_DROP: bool = os.getenv("AUTO_CONVERT_ON_DROP", "false").lower() == "true"
    AUTO_RESTART_ON_TRIGGER: bool = os.getenv("AUTO_RESTART_ON_TRIGGER", "false").lower() == "true"

    # ── Testnet REST & WebSocket base URLs ──
    TESTNET_REST_URL: str = "https://testnet.binance.vision/api"
    TESTNET_WS_URL: str = "wss://testnet.binance.vision/ws"


settings = Settings()

