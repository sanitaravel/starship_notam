"""Centralized configuration constants loaded from environment variables.

Uses python-dotenv to load a .env file from the project root. Exposes typed
constants consumed by all other packages.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (two levels up from this file:
# starship_notam/core/config.py -> starship_notam/ -> project root)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_dotenv_path = _PROJECT_ROOT / ".env"
load_dotenv(dotenv_path=str(_dotenv_path), override=True)

# --- Required configuration ---

TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip().strip('"')
if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError(
        "Required environment variable TELEGRAM_BOT_TOKEN is not set or is empty. "
        "Please set it in your .env file or system environment."
    )

# --- Optional configuration with defaults ---

_raw_chat_ids = os.environ.get("TELEGRAM_CHAT_ID", "")
CHAT_IDS: list[str] = [c.strip() for c in _raw_chat_ids.split(",") if c.strip()]

DB_PATH: str = os.environ.get("NOTAM_DB_PATH", "notams.db")

KEYWORD: str = os.environ.get("KEYWORD", "STARSHIP")

RUNS_PER_HOUR: int = int(os.environ.get("RUNS_PER_HOUR", "2"))

STATE_PATH: str = str(_PROJECT_ROOT / "telegram_chats.json")

# --- FCC ELS scraper configuration ---

FCC_ELS_SEARCH_URL: str = "https://apps.fcc.gov/oetcf/els/reports/GenericSearch.cfm"

FCC_ELS_SEARCH_TERM: str = "Space Exploration"

FCC_ELS_RECORD_LIMIT: int = 50
