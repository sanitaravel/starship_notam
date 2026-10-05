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
from starship_notam.data.connection import (
    get_connection,
    transaction,
    upsert,
    utc_now_iso,
)


def save_faa_activity(activity: Dict, db_path: Optional[str] = None) -> None:
    """Insert or update an FAA activity by *mission*.

    Uses a SHA-256 hash of the JSON-serialised payload to detect changes and
    maintains ``created_at`` / ``updated_at`` timestamps. A changed activity
    has ``telegram_posted`` reset so it is re-posted.
    """
    payload_hash = hashlib.sha256(
        json.dumps(activity, sort_keys=True).encode("utf-8")
    ).hexdigest()

    with transaction(get_connection(db_path)) as cur:
        result = upsert(
            cur,
            "faa_activities",
            "mission",
            activity["mission"],
            {
                "primary_window": activity["primary_window"],
                "backup_window": activity["backup_window"],
            },
            payload_hash,
            reset={"telegram_posted": 0},
        )
    logger.info("FAA activity '%s': %s", activity["mission"], result)


def get_faa_activities_needing_post(db_path: Optional[str] = None) -> List[Dict]:
    """Return FAA activities that have not yet been posted to Telegram."""
    logger.info("Fetching FAA activities needing Telegram posting")
    with transaction(get_connection(db_path)) as cur:
        cur.execute("""
            SELECT mission, primary_window, backup_window
            FROM faa_activities
            WHERE telegram_posted = 0
            ORDER BY created_at
        """)
        rows = cur.fetchall()

    logger.debug("Found %d FAA activities needing Telegram posting", len(rows))
    return [dict(r) for r in rows]


def mark_faa_activity_posted(mission, telegram_message_id, db_path: Optional[str] = None) -> None:
    """Mark an FAA activity as posted to Telegram with its message ID."""
    logger.info("Marking FAA activity '%s' as posted to Telegram with message ID %s", mission, telegram_message_id)
    with transaction(get_connection(db_path)) as cur:
        cur.execute("""
            UPDATE faa_activities
            SET telegram_posted = 1,
                telegram_posted_at = ?,
                telegram_message_id = ?
            WHERE mission = ?
        """, (utc_now_iso(), telegram_message_id, mission))
