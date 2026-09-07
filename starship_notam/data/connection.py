"""SQLite connection management and schema creation/migration logic.

Provides a connection factory and database initialization that creates all
required tables and performs schema migrations when needed.

This module does NOT import from Telegram, parsing, or visualization modules.
"""

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional

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


def init_db(db_path: Optional[str] = None) -> None:
    """Create the database tables if they don't exist and run migrations.

    Ensures that all required tables (notams, faa_activities, starbase_beach,
    starbase_road) exist and that their schemas are up-to-date. Legacy columns
    are migrated and removed as needed.

    On failure, any pending transaction is rolled back so the database is never
    left in a partially committed state.
    """
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()

        # --- notams table ---
        cur.execute(
            '''
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
            )
            '''
        )
        conn.commit()

        # --- faa_activities table ---
        cur.execute("""
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
            )
        """)
        conn.commit()

        # --- starbase_beach table ---
        cur.execute("""
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
            )
        """)
        conn.commit()

        cur.execute("PRAGMA table_info(starbase_beach)")
        beach_cols = [r['name'] for r in cur.fetchall()]
        if 'periods_json' not in beach_cols:
            cur.execute("ALTER TABLE starbase_beach ADD COLUMN periods_json TEXT")
            conn.commit()

        # --- starbase_road table ---
        cur.execute("""
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
            )
        """)
        conn.commit()

        # --- Legacy migration: parsed_json column removal ---
        cur.execute("PRAGMA table_info(notams)")
        cols = [r['name'] for r in cur.fetchall()]
        if 'parsed_json' in cols:
            logger.info('Detected legacy parsed_json column; migrating data into structured columns')
            cur.execute("SELECT id, parsed_json FROM notams WHERE parsed_json IS NOT NULL")
            rows = cur.fetchall()
            for r in rows:
                try:
                    payload = json.loads(r['parsed_json'])
                except Exception:
                    payload = {}
                q = payload.get('Q') if isinstance(payload, dict) else None
                updates = {
                    'A': payload.get('A'), 'B': payload.get('B'), 'C': payload.get('C'),
                    'D': payload.get('D'), 'E': payload.get('E'), 'F': payload.get('F'), 'G': payload.get('G'),
                    'Q_location': q.get('location') if isinstance(q, dict) else None,
                    'Q_q_code': q.get('q_code') if isinstance(q, dict) else None,
                    'Q_traffic': q.get('traffic') if isinstance(q, dict) else None,
                    'Q_traffic_rule': q.get('traffic_rule') if isinstance(q, dict) else None,
                    'Q_lower': q.get('lower') if isinstance(q, dict) else None,
                    'Q_upper': q.get('upper') if isinstance(q, dict) else None,
                    'Q_coordinates': q.get('coordinates') if isinstance(q, dict) else None,
                    'Q_radius_nm': q.get('radius_nm') if isinstance(q, dict) else None,
                }
                set_clause = ', '.join(f"{k} = ?" for k in updates.keys())
                params = list(updates.values()) + [r['id']]
                cur.execute(f"UPDATE notams SET {set_clause} WHERE id = ?", params)

            conn.commit()

            # Recreate table to drop parsed_json column (ensure final schema)
            logger.info('Recreating notams table to drop parsed_json column')
            final_cols = [
                'id', 'name', 'created_at', 'updated_at',
                'A', 'B', 'C', 'D', 'E', 'F', 'G',
                'Q_location', 'Q_q_code', 'Q_traffic', 'Q_traffic_rule',
                'Q_lower', 'Q_upper', 'Q_coordinates', 'Q_radius_nm',
                'parsed_hash', 'image_generated', 'image_generated_at'
            ]

            cur.execute('BEGIN')
            try:
                cur.execute(
                    '''
                    CREATE TABLE IF NOT EXISTS notams_new (
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
                    )
                    '''
                )
                existing_cols = cols
                cols_to_copy = [c for c in final_cols if c in existing_cols]
                cols_csv = ','.join(cols_to_copy)
                cur.execute(f"INSERT OR REPLACE INTO notams_new ({cols_csv}) SELECT {cols_csv} FROM notams")
                cur.execute('DROP TABLE notams')
                cur.execute('ALTER TABLE notams_new RENAME TO notams')
                cur.execute('COMMIT')
            except Exception:
                conn.rollback()
                raise

        # Ensure newer optional columns exist (add if missing)
        cur.execute("PRAGMA table_info(notams)")
        cols = [r['name'] for r in cur.fetchall()]
        if 'parsed_hash' not in cols:
            logger.info('Adding parsed_hash column to notams table')
            cur.execute("ALTER TABLE notams ADD COLUMN parsed_hash TEXT")
        if 'image_generated' not in cols:
            logger.info('Adding image_generated column to notams table')
            cur.execute("ALTER TABLE notams ADD COLUMN image_generated INTEGER DEFAULT 0")
        if 'image_generated_at' not in cols:
            logger.info('Adding image_generated_at column to notams table')
            cur.execute("ALTER TABLE notams ADD COLUMN image_generated_at TEXT")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
