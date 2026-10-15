"""Database schema: table definitions, column migrations and :func:`init_db`.

The schema is written for SQLite and adapted to PostgreSQL at run time.
Columns added after a table was first released are listed in
:data:`_ADDED_COLUMNS` and added with ``ALTER TABLE`` on start-up.
"""

from typing import Dict, Optional

from starship_notam.core.logging import logger
from starship_notam.data.connection import get_connection, transaction


# Written for SQLite; _schema_for() adapts it to PostgreSQL. The NOTAM field
# columns are quoted so PostgreSQL keeps their case (it lowercases unquoted
# names); SQLite treats the quoted and unquoted forms as the same column.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS notams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    "A" TEXT, "B" TEXT, "C" TEXT, "D" TEXT, "E" TEXT, "F" TEXT, "G" TEXT,
    "Q_location" TEXT, "Q_q_code" TEXT, "Q_traffic" TEXT, "Q_traffic_rule" TEXT,
    "Q_lower" TEXT, "Q_upper" TEXT, "Q_coordinates" TEXT, "Q_radius_nm" TEXT,
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

-- Files seen in the COMPASS (CADENA ATFM) "Master Slide Deck" list.
-- file_uuid is the site's fileuuid (UNIQUE key); a row is posted once, when
-- the file first appears (see compass_repo).
CREATE TABLE IF NOT EXISTS compass_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    file_uuid TEXT UNIQUE NOT NULL,

    filename TEXT,
    uploaded_at TEXT,

    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    payload_hash TEXT,

    telegram_posted INTEGER DEFAULT 0,
    telegram_posted_at TEXT,
    telegram_message_id TEXT
);

-- FAA documents mentioning SpaceX found in the Federal Register.
-- document_number is the Federal Register document number (UNIQUE key);
-- a row is posted once, when the document first appears (see
-- federal_register_repo).
CREATE TABLE IF NOT EXISTS federal_register_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    document_number TEXT UNIQUE NOT NULL,

    title TEXT,
    doc_type TEXT,
    abstract TEXT,
    publication_date TEXT,
    comments_close_on TEXT,
    html_url TEXT,
    pdf_url TEXT,

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


def _schema_for(conn) -> str:
    """Return :data:`_SCHEMA` in the SQL dialect of *conn*."""
    if getattr(conn, "is_postgres", False):
        return _SCHEMA.replace(
            "INTEGER PRIMARY KEY AUTOINCREMENT",
            "BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY",
        )
    return _SCHEMA


def _existing_columns(conn, cur, table: str) -> set:
    """Return the column names of *table*."""
    if getattr(conn, "is_postgres", False):
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = ?",
            (table,),
        )
        return {r["column_name"] for r in cur.fetchall()}
    cur.execute(f"PRAGMA table_info({table})")
    return {r["name"] for r in cur.fetchall()}


def _ensure_columns(conn, cur, table: str, spec: Dict[str, str]) -> None:
    """Add each column in *spec* (name -> SQL type) that *table* lacks."""
    existing = _existing_columns(conn, cur, table)
    for col_name, col_def in spec.items():
        if col_name not in existing:
            logger.info("Adding %s column to %s table", col_name, table)
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")


def init_db(db_path: Optional[str] = None) -> None:
    """Create the database tables if they don't exist and add missing columns.

    Ensures that all required tables (notams, faa_activities, starbase_beach,
    starbase_road, fcc_els_applications, faa_licenses, compass_files,
    federal_register_documents) exist and have every
    column listed in ``_ADDED_COLUMNS``.

    On failure, any pending transaction is rolled back so the database is never
    left in a partially committed state.
    """
    conn = get_connection(db_path)
    with transaction(conn) as cur:
        conn.executescript(_schema_for(conn))
        for table, spec in _ADDED_COLUMNS.items():
            _ensure_columns(conn, cur, table, spec)
