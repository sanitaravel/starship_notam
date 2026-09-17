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

# --- FAA DRS launch-license tracker configuration ---

# Base host used to resolve DRS API/document URLs.
FAA_LICENSE_BASE_URL: str = "https://drs.faa.gov"

# The DRS document unique id (DRSDOCID...) for the Starship / Super Heavy
# Vehicle Operator License we track. Overridable via the environment so a
# different license document can be followed without a code change.
FAA_LICENSE_DOC_ID: str = os.environ.get(
    "FAA_LICENSE_DOC_ID",
    "DRSDOCID173891218620231102140506.0001",
).strip()

# The human-facing DRS document viewer URL (the page a reader would open). Used
# both to establish WAF/session cookies in the browser and as the "source"
# link in Telegram notifications.
FAA_LICENSE_VIEWER_URL: str = (
    f"{FAA_LICENSE_BASE_URL}/browse/excelExternalWindow/{FAA_LICENSE_DOC_ID}"
)

# The DRS JSON summary API returning the document's metadata ("Document
# Details" panel). Queried from within the browser context after the viewer
# page has loaded so the Akamai/AWS session cookies are attached.
FAA_LICENSE_SUMMARY_URL: str = (
    f"{FAA_LICENSE_BASE_URL}"
    f"/api/browse/documents/summaryguiddocview/{FAA_LICENSE_DOC_ID}"
)
