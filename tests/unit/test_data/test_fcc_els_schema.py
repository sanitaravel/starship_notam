"""Schema tests for the ``fcc_els_applications`` table (``data.connection``).

Exercises :func:`starship_notam.data.connection.init_db` against an isolated
temporary SQLite database (via the ``db_path`` fixture) to verify table
creation, the ``file_number`` UNIQUE constraint, idempotent re-initialisation,
and the additive column migration.

Covers Requirements 6.1, 6.2, 6.3, 6.4, 6.5.
"""

from __future__ import annotations

import sqlite3

import pytest

from starship_notam.data.connection import get_connection, init_db, utc_now_iso


# The full set of columns the table must expose after init_db (Req 6.3).
EXPECTED_COLUMNS = {
    "id",
    "file_number",
    "application_seq",
    "applicant_name",
    "call_sign",
    "receipt_date",
    "status",
    "status_date",
    "current_detail_url",
    "detail_json",
    "created_at",
    "updated_at",
    "payload_hash",
    "telegram_posted",
    "telegram_posted_at",
    "telegram_message_id",
}


def _table_columns(conn, table="fcc_els_applications"):
    """Return the set of column names for *table* via PRAGMA table_info."""
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    return {row["name"] for row in cur.fetchall()}


def _insert_application(conn, file_number, **overrides):
    """Insert a minimal valid fcc_els_applications row and commit it."""
    now = utc_now_iso()
    values = {
        "file_number": file_number,
        "application_seq": "12345",
        "applicant_name": "Space Exploration Technologies Corp.",
        "call_sign": "",
        "receipt_date": "01/01/2025",
        "status": "Granted",
        "status_date": "01/15/2025",
        "current_detail_url": "https://apps.fcc.gov/oetcf/els/reports/STA_Print.cfm",
        "detail_json": "{}",
        "created_at": now,
        "updated_at": now,
        "payload_hash": "deadbeef",
        "telegram_posted": 0,
        "telegram_posted_at": None,
        "telegram_message_id": None,
    }
    values.update(overrides)
    cols = ", ".join(values.keys())
    placeholders = ", ".join("?" for _ in values)
    conn.execute(
        f"INSERT INTO fcc_els_applications ({cols}) VALUES ({placeholders})",
        tuple(values.values()),
    )
    conn.commit()


def test_init_db_creates_table_with_expected_columns(db_path):
    """init_db on a fresh DB creates the table with the full column set.

    Validates Requirements 6.1, 6.3.
    """
    init_db(db_path)

    conn = get_connection(db_path)
    try:
        # The table exists.
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = 'fcc_els_applications'"
        )
        assert cur.fetchone() is not None

        assert _table_columns(conn) == EXPECTED_COLUMNS
    finally:
        conn.close()


def test_init_db_enforces_file_number_unique_constraint(db_path):
    """Inserting a second row with an existing file_number is rejected.

    Validates Requirement 6.4.
    """
    init_db(db_path)

    conn = get_connection(db_path)
    try:
        _insert_application(conn, "0123-EX-ST-2025")

        with pytest.raises(sqlite3.IntegrityError):
            _insert_application(conn, "0123-EX-ST-2025", application_seq="99999")
    finally:
        conn.close()


def test_init_db_twice_preserves_existing_row(db_path):
    """Running init_db again leaves an already-inserted row unchanged.

    Validates Requirement 6.2.
    """
    init_db(db_path)

    conn = get_connection(db_path)
    try:
        _insert_application(conn, "0456-EX-ST-2025", applicant_name="SpaceX")
    finally:
        conn.close()

    # Re-run initialisation; it must not drop or recreate the table.
    init_db(db_path)

    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT file_number, applicant_name FROM fcc_els_applications"
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    assert len(rows) == 1
    assert rows[0]["file_number"] == "0456-EX-ST-2025"
    assert rows[0]["applicant_name"] == "SpaceX"


def test_init_db_additively_migrates_partial_table(db_path):
    """A pre-existing partial table gains missing columns without losing rows.

    Validates Requirement 6.5.
    """
    # Pre-create a partial fcc_els_applications table with only a subset of the
    # expected columns, then insert a row directly.
    conn = get_connection(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE fcc_els_applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_number TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        now = utc_now_iso()
        conn.execute(
            "INSERT INTO fcc_els_applications "
            "(file_number, created_at, updated_at) VALUES (?, ?, ?)",
            ("0789-EX-ST-2025", now, now),
        )
        conn.commit()

        partial_cols = _table_columns(conn)
        # Sanity: the partial table is genuinely missing columns.
        assert "applicant_name" not in partial_cols
        assert "telegram_posted" not in partial_cols
    finally:
        conn.close()

    # Run the migration.
    init_db(db_path)

    conn = get_connection(db_path)
    try:
        # All expected columns are now present (additively added).
        assert EXPECTED_COLUMNS.issubset(_table_columns(conn))

        # The pre-existing row survives the migration intact.
        cur = conn.cursor()
        cur.execute(
            "SELECT file_number FROM fcc_els_applications"
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    assert len(rows) == 1
    assert rows[0]["file_number"] == "0789-EX-ST-2025"
