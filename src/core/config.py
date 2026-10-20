"""Centralized configuration constants loaded from environment variables.

Uses python-dotenv to load a .env file from the project root. Exposes typed
constants consumed by all other packages.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (two levels up from this file:
# src/core/config.py -> src/ -> project root), or the
# file named by NOTAM_ENV_FILE (the test suite uses .env.test, so tests and
# manual checks never pick up the real token or database).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_dotenv_path = Path(os.environ.get("NOTAM_ENV_FILE") or _PROJECT_ROOT / ".env")
load_dotenv(dotenv_path=str(_dotenv_path), override=True)

# --- Required configuration ---

TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip().strip('"')
if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError(
        "Required environment variable TELEGRAM_BOT_TOKEN is not set or is empty. "
        "Please set it in your .env file or system environment."
    )

# The single Telegram channel the bot posts to. Set only in .env. Use the
# channel's numeric id (typically the -100... form) or its public @username.
# The bot must be an administrator of the channel with permission to post.
TELEGRAM_CHANNEL_ID: str = os.environ.get("TELEGRAM_CHANNEL_ID", "").strip().strip('"')
if not TELEGRAM_CHANNEL_ID:
    raise RuntimeError(
        "Required environment variable TELEGRAM_CHANNEL_ID is not set or is empty. "
        "Please set it in your .env file or system environment."
    )

# --- Optional configuration with defaults ---

# Database target: a PostgreSQL URL (postgresql://user:pass@host:5432/db) when
# DATABASE_URL is set, otherwise the SQLite file at NOTAM_DB_PATH.
DB_PATH: str = (
    os.environ.get("DATABASE_URL", "").strip()
    or os.environ.get("NOTAM_DB_PATH", "notams.db")
)

KEYWORD: str = os.environ.get("KEYWORD", "STARSHIP")

RUNS_PER_HOUR: int = int(os.environ.get("RUNS_PER_HOUR", "2"))

# Commit the running image was built from (set by the Dockerfile from the
# GIT_SHA build argument); "dev" outside a CI-built image.
VERSION: str = os.environ.get("NOTAM_VERSION", "dev")

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

# The human-facing DRS document viewer URL (the page a reader would open), used
# as the "source" link in Telegram notifications.
FAA_LICENSE_VIEWER_URL: str = (
    f"{FAA_LICENSE_BASE_URL}/browse/excelExternalWindow/{FAA_LICENSE_DOC_ID}"
)

# Guest login: redirects to targetUrl and sets the jwt/user cookies the
# summary API requires.
FAA_LICENSE_GUEST_LOGIN_URL: str = (
    f"{FAA_LICENSE_BASE_URL}/guest/login?targetUrl=/browse"
)

# The DRS JSON summary API returning the document's metadata ("Document
# Details" panel). Needs the guest token in the jwt/user request headers.
FAA_LICENSE_SUMMARY_URL: str = (
    f"{FAA_LICENSE_BASE_URL}"
    f"/api/browse/documents/summaryguiddocview/{FAA_LICENSE_DOC_ID}"
)

# --- COMPASS (CADENA ATFM) Master Slide Deck tracker configuration ---

# Base host of the COMPASS public portal.
COMPASS_BASE_URL: str = "https://compass.atfm.aero"

# The JSON endpoint that fills the "Master Slide Deck" grid on
# vpublic_anspdetail.jsp?view=3 (one row per uploaded file).
COMPASS_SLIDE_LIST_URL: str = (
    f"{COMPASS_BASE_URL}/public_svcdynamic/?key=public_getpublicslidelist"
)

# --- Federal Register (FAA documents mentioning SpaceX) configuration ---

# Public Federal Register search API (no key needed, plain JSON).
FEDERAL_REGISTER_API_URL: str = "https://www.federalregister.gov/api/v1/documents.json"

# Query sent to FEDERAL_REGISTER_API_URL: the newest FAA documents whose text
# mentions SpaceX, with only the fields the bot posts.
FEDERAL_REGISTER_PARAMS: dict = {
    "conditions[agencies][]": "federal-aviation-administration",
    "conditions[term]": "spacex",
    "order": "newest",
    "per_page": 20,
    "fields[]": [
        "document_number",
        "title",
        "type",
        "abstract",
        "publication_date",
        "html_url",
        "pdf_url",
        "comments_close_on",
    ],
}

# --- Regulations.gov (FAA/USCG Starship docket documents) configuration ---

# api.data.gov key for the Regulations.gov API (free sign-up at
# https://open.gsa.gov/api/regulationsgov/). The source is skipped while unset.
REGULATIONS_GOV_API_KEY: str = (
    os.environ.get("REGULATIONS_GOV_API_KEY", "").strip().strip('"')
)

REGULATIONS_GOV_API_URL: str = "https://api.regulations.gov/v4"

# One search per term, merged by document id: "Starship" alone misses e.g. the
# USCG "Rocket Test Site" safety zone at Boca Chica.
REGULATIONS_GOV_SEARCH_TERMS: tuple = ("SpaceX", "Starship", "Boca Chica", "Starbase")

# Query sent with each search term: the newest FAA and USCG documents (other
# agencies, mostly EPA, only add noise for these terms).
REGULATIONS_GOV_PARAMS: dict = {
    "filter[agencyId]": "FAA,USCG",
    "sort": "-postedDate",
    "page[size]": 25,
}

# --- SEC EDGAR (SpaceX filings as a public company) configuration ---

# User-Agent sent to SEC, which blocks requests without a descriptive one
# naming a contact, e.g. "starship_notam bot admin@example.org"
# (https://www.sec.gov/os/accessing-edgar-data). The source is skipped while
# unset.
SEC_USER_AGENT: str = os.environ.get("SEC_USER_AGENT", "").strip().strip('"')

# Space Exploration Technologies Corp (Nasdaq: SPCX).
SEC_EDGAR_CIK: str = "0001181412"

# Every filing of the company, newest first (one request per cycle).
SEC_EDGAR_SUBMISSIONS_URL: str = (
    f"https://data.sec.gov/submissions/CIK{SEC_EDGAR_CIK}.json"
)

# Forms that are posted: material events, periodic reports (with late-filing
# notices) and securities offerings, plus their amendments. Insider forms
# (3/4/144), 13G, S-8, Form D and SEC correspondence are left out: frequent
# and never about Starship.
SEC_EDGAR_FORMS: tuple = (
    "8-K", "8-K/A",
    "10-Q", "10-Q/A", "NT 10-Q",
    "10-K", "10-K/A", "NT 10-K",
    "S-1", "S-1/A", "S-3", "S-3/A",
    "424B1", "424B2", "424B3", "424B4", "424B5", "424B7", "424B8",
)
