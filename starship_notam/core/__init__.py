"""Core package: centralized configuration and logging for Starship NOTAM.

Re-exports key objects from config and logging modules for convenient access:
    from starship_notam.core import logger, console, TELEGRAM_BOT_TOKEN, ...
"""

from starship_notam.core.config import (
    CHAT_IDS,
    DB_PATH,
    KEYWORD,
    RUNS_PER_HOUR,
    STATE_PATH,
    TELEGRAM_BOT_TOKEN,
)
from starship_notam.core.logging import console, logger

__all__ = [
    "TELEGRAM_BOT_TOKEN",
    "CHAT_IDS",
    "DB_PATH",
    "KEYWORD",
    "RUNS_PER_HOUR",
    "STATE_PATH",
    "logger",
    "console",
]
