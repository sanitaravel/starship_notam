"""Shared logging configuration for the Starship NOTAM project.

Exposes a pre-configured `logger` instance with both a Rich console handler
and a rotating file handler writing to `logs/notam.log`. Also exposes a
shared `rich.console.Console` instance.
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

# Shared Rich console instance
console = Console()

# Ensure a logs directory exists relative to the project root
LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
try:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    # If we cannot create a logs directory, continue but file logging will be skipped
    LOG_DIR = None

LOG_FILE = (LOG_DIR / "notam.log") if LOG_DIR is not None else None

# Create or get a dedicated logger for the project
logger = logging.getLogger("notam")
logger.setLevel(logging.INFO)

# Add a Rich console handler if not already present
if not any(isinstance(h, RichHandler) for h in logger.handlers):
    try:
        rich_handler = RichHandler(rich_tracebacks=True)
        rich_handler.setLevel(logging.INFO)
        logger.addHandler(rich_handler)
    except Exception:
        # Fall back to basic config if RichHandler setup fails
        logging.basicConfig(level=logging.INFO, format="%(message)s")

# Add a rotating file handler to persist logs
if LOG_FILE is not None and not any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
    try:
        # Open the log file in write mode so each run overwrites previous logs
        file_handler = RotatingFileHandler(
            str(LOG_FILE), mode="w", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setLevel(logging.INFO)
        file_formatter = logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    except Exception:
        # If file handler cannot be created, continue without file logging
        logger.exception("Failed to initialize file logging; continuing without file handler")

# Avoid double-propagation to the root logger
logger.propagate = False
