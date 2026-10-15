"""Database connections, transactions and the change-detecting upsert.

Two backends are supported: SQLite (a file path) and PostgreSQL (a ``postgresql://`` URL). The
repositories write SQLite-style SQL (``?`` placeholders, rows read by column
name); the PostgreSQL connection is wrapped so the same SQL runs on both.
psycopg is imported lazily, so it is only needed when PostgreSQL is used.

The table definitions and :func:`init_db` live in
:mod:`src.data.schema`.

This module does NOT import from Telegram, parsing, or visualization modules.
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Generator, Optional

from src.core.config import DB_PATH


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with a "Z" suffix.

    Uses a timezone-aware UTC datetime (``datetime.now(timezone.utc)``) rather
    than the deprecated ``datetime.utcnow()``. The tzinfo is stripped before
    formatting so the output keeps the historical ``...Z`` shape (e.g.
    ``2024-01-01T00:00:00Z``) instead of ``+00:00``, preserving the exact
    string format previously stored in the database.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"


_POSTGRES_SCHEMES = ("postgresql://", "postgres://")


def is_postgres(db_path: str) -> bool:
    """Return True when *db_path* is a PostgreSQL URL rather than a file path."""
    return db_path.startswith(_POSTGRES_SCHEMES)


class _PgCursor:
    """psycopg cursor that accepts the ``?`` placeholders used by the repositories."""

    def __init__(self, cur):
        self._cur = cur

    def execute(self, sql: str, params=None):
        if params:
            sql = sql.replace("?", "%s")
        self._cur.execute(sql, params or None)
        return self

    def __getattr__(self, name):
        return getattr(self._cur, name)


class _PgConnection:
    """psycopg connection exposing the parts of the sqlite3 API the data layer uses."""

    is_postgres = True

    def __init__(self, conn):
        self._conn = conn

    def cursor(self) -> _PgCursor:
        return _PgCursor(self._conn.cursor())

    def executescript(self, script: str) -> None:
        # Without parameters psycopg sends the text as-is, so several
        # statements can run in one call.
        self._conn.execute(script)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def resolve_db_path(db_path: Optional[str] = None) -> str:
    """Return *db_path*, or the configured database when it is *None*.

    The fallback is read from the ``DATABASE_URL`` environment variable, then
    ``NOTAM_DB_PATH``, then :data:`core.config.DB_PATH`.
    """
    return (
        db_path
        or os.environ.get("DATABASE_URL")
        or os.environ.get("NOTAM_DB_PATH")
        or DB_PATH
    )


def get_connection(db_path: Optional[str] = None):
    """Return a new database connection whose rows are readable by column name.

    Parameters
    ----------
    db_path : str or None
        A PostgreSQL URL (``postgresql://...``) or the path to a SQLite file.
        When *None*, it is resolved by :func:`resolve_db_path`.
    """
    path = resolve_db_path(db_path)
    if is_postgres(path):
        import psycopg
        from psycopg.rows import dict_row

        return _PgConnection(psycopg.connect(path, row_factory=dict_row, connect_timeout=30))

    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def transaction(conn) -> Generator[sqlite3.Cursor, None, None]:
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
        set_clause = ", ".join(f'"{c}" = ?' for c in cols)
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
        f"INSERT INTO {table} ({', '.join(f'"{c}"' for c in cols)}) VALUES ({placeholders})",
        list(cols.values()),
    )
    return "inserted"
