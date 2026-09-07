"""FAA activity persistence functions — save, query, and update FAA records.

Provides CRUD-like operations for the ``faa_activities`` table. Functions
accept and return plain Python dictionaries; no domain models are required.

This module imports only from ``starship_notam.data.connection``,
``starship_notam.core``, and the Python standard library.
"""

import hashlib
import json
from typing import Dict, List, Optional

from starship_notam.core.logging import logger
from starship_notam.data.connection import get_connection, init_db, utc_now_iso


def save_faa_activity(activity: Dict, db_path: Optional[str] = None) -> None:
    """Insert or update an FAA activity by *mission*.

    Uses a SHA-256 hash of the JSON-serialised payload to detect changes and
    maintains ``created_at`` / ``updated_at`` timestamps.
    """
    init_db(db_path)
    payload_hash = hashlib.sha256(
        json.dumps(activity, sort_keys=True).encode("utf-8")
    ).hexdigest()

    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT payload_hash
            FROM faa_activities
            WHERE mission = ?
            """, (activity["mission"],))
        activity_existing = cur.fetchone()
    except Exception as e:
        logger.exception(f"Error checking existing FAA activity: {e}")
        activity_existing = None

    try:
        if activity_existing:
            logger.info(f"FAA activity for mission '{activity['mission']}' already exists; checking for updates")

            existing_hash = activity_existing['payload_hash']

            if existing_hash is not None and payload_hash is not None and existing_hash == payload_hash:
                logger.info(f"No changes detected for FAA activity '{activity['mission']}'; skipping DB update")
                return
            else:
                if existing_hash == payload_hash:
                    logger.info(f"No effective changes detected for FAA activity '{activity['mission']}'; refreshing updated_at")
                    update_cols = ['updated_at']
                    update_set = ', '.join(f"{c} = ?" for c in update_cols)
                    update_params = [utc_now_iso(), activity['mission']]
                    cur.execute(f"UPDATE faa_activities SET {update_set} WHERE mission = ?", update_params)
                else:
                    logger.info(f"Changes detected for FAA activity '{activity['mission']}'; updating all fields")
                    update_cols = ['primary_window', 'backup_window', 'updated_at', 'payload_hash']
                    update_set = ', '.join(f"{c} = ?" for c in update_cols)
                    update_params = [
                        activity['primary_window'],
                        activity['backup_window'],
                        utc_now_iso(),
                        payload_hash,
                        activity['mission']
                    ]
                    cur.execute(f"UPDATE faa_activities SET {update_set} WHERE mission = ?", update_params)
        else:
            logger.info(f"Inserting new FAA activity for mission '{activity['mission']}'")
            cur.execute("""
                INSERT INTO faa_activities (mission, primary_window, backup_window, created_at, updated_at, payload_hash)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                activity["mission"],
                activity["primary_window"],
                activity["backup_window"],
                utc_now_iso(),
                utc_now_iso(),
                payload_hash
            ))
    finally:
        conn.commit()
        conn.close()


def get_faa_activities_needing_post(db_path: Optional[str] = None) -> List[Dict]:
    """Return FAA activities that have not yet been posted to Telegram."""
    logger.info("Fetching FAA activities needing Telegram posting")
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT mission, primary_window, backup_window
            FROM faa_activities
            WHERE telegram_posted = 0
            ORDER BY created_at
        """)
        rows = cur.fetchall()

        logger.debug("Found %d FAA activities needing Telegram posting", len(rows))
        return [
            {
                "mission": r["mission"],
                "primary_window": r["primary_window"],
                "backup_window": r["backup_window"]
            }
            for r in rows
        ]
    finally:
        conn.close()


def mark_faa_activity_posted(mission, telegram_message_id, db_path: Optional[str] = None) -> None:
    """Mark an FAA activity as posted to Telegram with its message ID."""
    logger.info("Marking FAA activity '%s' as posted to Telegram with message ID %s", mission, telegram_message_id)
    now = utc_now_iso()

    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE faa_activities
            SET telegram_posted = 1,
                telegram_posted_at = ?,
                telegram_message_id = ?
            WHERE mission = ?
        """, (now, telegram_message_id, mission))
        conn.commit()
    finally:
        conn.close()
