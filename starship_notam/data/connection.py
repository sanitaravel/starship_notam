"""SQLite connection management and schema creation/migration logic.

Provides a connection factory and database initialization that creates all
required tables and performs schema migrations when needed.

This module does NOT import from Telegram, parsing, or visualization modules.
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Generator, Optional

from starship_notam.core.config import DB_PATH
from starship_notam.core.logging import logger


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with a "Z" suffix.

    Uses a timezone-aware UTC datetime (``datetime.now(timezone.utc)``) rather
    than the deprecated ``datetime.utcnow()``. The tzinfo is stripped before
    formatting so the output keeps the historical ``...Z`` shape (e.g.
    ``2024-01-01T00:00:00Z``) instead of ``+00:00``, preserving the exact
    string format previously stored in the database.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Return a new SQLite connection with Row factory enabled.

    Parameters
    ----------
    db_path : str or None
        Explicit path to the database file. When *None*, the path is resolved
        by reading the ``NOTAM_DB_PATH`` environment variable; if that variable
        is not set, falls back to :data:`core.config.DB_PATH` (default
        ``"notams.db"``).
    """
    path = db_path or os.environ.get("NOTAM_DB_PATH") or DB_PATH
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Generator[sqlite3.Cursor, None, None]:
    """Yield a cursor on *conn*; commit on success, roll back on error, always close.

    Takes an already-open connection (rather than opening one) so each
    repository keeps using its own ``get_connection`` reference.
    """
    try:
        yield conn.cursor()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def upsert(
    cur: sqlite3.Cursor,
    table: str,
    key_col: str,
    key,
    fields: Dict[str, Any],
    payload_hash: Optional[str],
    reset: Optional[Dict[str, Any]] = None,
    hash_col: str = "payload_hash",
) -> str:
    """Insert or update the row of *table* whose *key_col* equals *key*.

    An existing row with the same stored hash is left untouched. Otherwise
    *fields*, ``updated_at`` and the hash are written, plus the *reset*
    columns (e.g. ``{"telegram_posted": 0}``) so the changed row is
    processed again. New rows also get ``created_at`` and the *reset* values.

    Returns ``"unchanged"``, ``"updated"`` or ``"inserted"``.
    """
    cur.execute(f"SELECT {hash_col} FROM {table} WHERE {key_col} = ?", (key,))
    existing = cur.fetchone()
    if existing and payload_hash is not None and existing[hash_col] == payload_hash:
        return "unchanged"

    now = utc_now_iso()
    if existing:
        cols = {**fields, "updated_at": now, hash_col: payload_hash, **(reset or {})}
        set_clause = ", ".join(f"{c} = ?" for c in cols)
        cur.execute(
            f"UPDATE {table} SET {set_clause} WHERE {key_col} = ?",
            [*cols.values(), key],
        )
        return "updated"

    cols = {
        key_col: key,
        **fields,
        "created_at": now,
        "updated_at": now,
        hash_col: payload_hash,
        **(reset or {}),
    }
    placeholders = ", ".join("?" for _ in cols)
    cur.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})",
        list(cols.values()),
    )
    return "inserted"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS notams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    A TEXT, B TEXT, C TEXT, D TEXT, E TEXT, F TEXT, G TEXT,
    Q_location TEXT, Q_q_code TEXT, Q_traffic TEXT, Q_traffic_rule TEXT,
    Q_lower TEXT, Q_upper TEXT, Q_coordinates TEXT, Q_radius_nm TEXT,
    parsed_hash TEXT,
    image_generated INTEGER DEFAULT 0,
    image_generated_at TEXT
);

CREATE TABLE IF NOT EXISTS faa_activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    mission TEXT NOT NULL,
    primary_window TEXT,
    backup_window TEXT,

    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    payload_hash TEXT,

    telegram_posted INTEGER DEFAULT 0,
    telegram_posted_at TEXT,
    telegram_message_id TEXT,

    UNIQUE(mission, primary_window)
);

CREATE TABLE IF NOT EXISTS starbase_beach (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    alert_key TEXT UNIQUE NOT NULL,

    description TEXT,

    is_closed INTEGER DEFAULT 0,

    start_utc TEXT,
    end_utc TEXT,

    raw_date TEXT,
    periods_json TEXT,

    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    payload_hash TEXT,

    processed INTEGER DEFAULT 0,
    processed_at TEXT
);

CREATE TABLE IF NOT EXISTS starbase_road (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    alert_key TEXT UNIQUE NOT NULL,

    origin TEXT,
    destination TEXT,

    description TEXT,

    start_utc TEXT,
    end_utc TEXT,

    raw_date TEXT,

    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    payload_hash TEXT,

    processed INTEGER DEFAULT 0,
    processed_at TEXT
);

CREATE TABLE IF NOT EXISTS fcc_els_applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    file_number TEXT UNIQUE NOT NULL,

    application_seq TEXT,
    applicant_name TEXT,
    call_sign TEXT,
    receipt_date TEXT,
    status TEXT,
    status_date TEXT,

    current_detail_url TEXT,
    detail_json TEXT,

    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    payload_hash TEXT,

    telegram_posted INTEGER DEFAULT 0,
    telegram_posted_at TEXT,
    telegram_message_id TEXT
);

-- Tracks a single FAA DRS launch (Vehicle Operator) license document.
-- doc_unique_id is the stable DRSDOCID identifier (UNIQUE key);
-- content_guid is the underlying content object id which changes when the
-- file is re-uploaded; details_json holds the ordered "Document Details"
-- panel. Change detection uses payload_hash and resets telegram_posted to 0
-- on any change (see faa_license_repo).
CREATE TABLE IF NOT EXISTS faa_licenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    doc_unique_id TEXT UNIQUE NOT NULL,

    content_guid TEXT,
    doc_number TEXT,
    doc_name TEXT,
    doc_type_label TEXT,

    status TEXT,
    revision_number TEXT,
    issue_date TEXT,
    expiration_date TEXT,

    details_json TEXT,

    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    payload_hash TEXT,

    telegram_posted INTEGER DEFAULT 0,
    telegram_posted_at TEXT,
    telegram_message_id TEXT
);
"""

# Columns added after a table was first released. Databases created before
# then get them via ALTER TABLE ... ADD COLUMN (no table rebuild needed).
_ADDED_COLUMNS = {
    "notams": {
        "parsed_hash": "TEXT",
        "image_generated": "INTEGER DEFAULT 0",
        "image_generated_at": "TEXT",
    },
    "starbase_beach": {
        "periods_json": "TEXT",
    },
    "fcc_els_applications": {
        "application_seq": "TEXT",
        "applicant_name": "TEXT",
        "call_sign": "TEXT",
        "receipt_date": "TEXT",
        "status": "TEXT",
        "status_date": "TEXT",
        "current_detail_url": "TEXT",
        "detail_json": "TEXT",
        "payload_hash": "TEXT",
        "telegram_posted": "INTEGER DEFAULT 0",
        "telegram_posted_at": "TEXT",
        "telegram_message_id": "TEXT",
    },
    "faa_licenses": {
        "content_guid": "TEXT",
        "doc_number": "TEXT",
        "doc_name": "TEXT",
        "doc_type_label": "TEXT",
        "status": "TEXT",
        "revision_number": "TEXT",
        "issue_date": "TEXT",
        "expiration_date": "TEXT",
        "details_json": "TEXT",
        "payload_hash": "TEXT",
        "telegram_posted": "INTEGER DEFAULT 0",
        "telegram_posted_at": "TEXT",
        "telegram_message_id": "TEXT",
    },
}


def _ensure_columns(cur: sqlite3.Cursor, table: str, spec: Dict[str, str]) -> None:
    """Add each column in *spec* (name -> SQL type) that *table* lacks."""
    cur.execute(f"PRAGMA table_info({table})")
    existing = {r["name"] for r in cur.fetchall()}
    for col_name, col_def in spec.items():
        if col_name not in existing:
            logger.info("Adding %s column to %s table", col_name, table)
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")


def init_db(db_path: Optional[str] = None) -> None:
    """Create the database tables if they don't exist and add missing columns.

    Ensures that all required tables (notams, faa_activities, starbase_beach,
    starbase_road, fcc_els_applications, faa_licenses) exist and have every
    column listed in ``_ADDED_COLUMNS``.

    On failure, any pending transaction is rolled back so the database is never
    left in a partially committed state.
    """
    conn = get_connection(db_path)
    with transaction(conn) as cur:
        conn.executescript(_SCHEMA)
        for table, spec in _ADDED_COLUMNS.items():
            _ensure_columns(cur, table, spec)
