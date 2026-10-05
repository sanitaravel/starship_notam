"""COMPASS Master Slide Deck persistence functions — save, query, and update.

Provides operations for the ``compass_files`` table, which records every file
seen in the COMPASS "Master Slide Deck" list, keyed by the site's
``fileuuid``. Only *new* files are posted: a changed name or upload time on an
already-known file is stored but does not re-flag it for posting.

This module imports only from ``starship_notam.data.connection``,
``starship_notam.core``, and the Python standard library.
"""

import hashlib
import json
from typing import Dict, Iterable, List, Optional

from starship_notam.core.logging import logger
from starship_notam.data.connection import (
    get_connection,
    transaction,
    upsert,
    utc_now_iso,
)


def save_compass_file(record: Dict, db_path: Optional[str] = None) -> str:
    """Insert or update a COMPASS file by ``file_uuid``.

    New files are inserted with ``telegram_posted = 0``; existing files keep
    their posting state. Returns ``"inserted"``, ``"updated"``,
    ``"unchanged"`` or ``"skipped"`` (record without ``file_uuid``).
    """
    file_uuid = str((record or {}).get("file_uuid") or "").strip()
    if not file_uuid:
        logger.info("save_compass_file: record missing file_uuid; skipping")
        return "skipped"

    fields = {
        "filename": record.get("filename"),
        "uploaded_at": record.get("uploaded_at"),
    }
    payload_hash = hashlib.sha256(
        json.dumps(fields, sort_keys=True).encode("utf-8")
    ).hexdigest()

    with transaction(get_connection(db_path)) as cur:
        result = upsert(cur, "compass_files", "file_uuid", file_uuid, fields, payload_hash)
    logger.info("COMPASS file '%s': %s", file_uuid, result)
    return result


def get_compass_files_needing_post(db_path: Optional[str] = None) -> List[Dict]:
    """Return COMPASS files not yet posted to Telegram, in insertion order."""
    logger.info("Fetching COMPASS files needing Telegram posting")
    with transaction(get_connection(db_path)) as cur:
        cur.execute(
            """
            SELECT id,
                   file_uuid,
                   filename,
                   uploaded_at,
                   created_at,
                   updated_at,
                   telegram_posted,
                   telegram_posted_at,
                   telegram_message_id
            FROM compass_files
            WHERE telegram_posted = 0
            ORDER BY id
            """
        )
        return [dict(r) for r in cur.fetchall()]


def mark_compass_file_posted(
    file_uuid, telegram_message_id, db_path: Optional[str] = None
) -> None:
    """Mark a COMPASS file as posted to Telegram with its message ID."""
    logger.info(
        "Marking COMPASS file '%s' as posted to Telegram with message ID %s",
        file_uuid,
        telegram_message_id,
    )
    mark_compass_files_posted([file_uuid], telegram_message_id, db_path)


def mark_compass_files_posted(
    file_uuids: Iterable[str],
    telegram_message_id=None,
    db_path: Optional[str] = None,
) -> int:
    """Mark several COMPASS files as posted; return how many rows changed.

    Rows already marked posted are left alone, so their recorded message IDs
    are kept. Called with ``telegram_message_id=None`` to prefill the database
    with files that should never be announced.
    """
    now = utc_now_iso()
    changed = 0
    with transaction(get_connection(db_path)) as cur:
        for file_uuid in file_uuids:
            cur.execute(
                """
                UPDATE compass_files
                SET telegram_posted = 1,
                    telegram_posted_at = ?,
                    telegram_message_id = ?
                WHERE file_uuid = ? AND telegram_posted = 0
                """,
                (now, telegram_message_id, file_uuid),
            )
            changed += cur.rowcount
    return changed
