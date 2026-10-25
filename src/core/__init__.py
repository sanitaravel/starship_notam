"""Core package: centralized configuration and logging for Starship NOTAM.

Re-exports key objects from config and logging modules for convenient access:
    from src.core import logger, console, TELEGRAM_BOT_TOKEN, ...
"""

from src.core.config import (
    DB_PATH,
    DISCORD_WEBHOOK_URL,
    KEYWORD,
    RUNS_PER_HOUR,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHANNEL_ID,
)
from src.core.logging import console, logger

__all__ = [
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHANNEL_ID",
    "DISCORD_WEBHOOK_URL",
    "DB_PATH",
    "KEYWORD",
    "RUNS_PER_HOUR",
    "logger",
    "console",
]
