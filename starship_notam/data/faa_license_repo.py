"""FAA DRS launch-license persistence functions — save, query, and update.

Provides CRUD-like operations for the ``faa_licenses`` table, which tracks a
single FAA DRS launch (Vehicle Operator) license document and its "Document
Details" metadata. Functions accept and return plain Python dictionaries; no
domain models are required.

Change detection mirrors the FCC ELS repository: a deterministic SHA-256
``payload_hash`` is computed over the tracked fields; unchanged records are
left untouched, and changed records have all fields refreshed, ``updated_at``
bumped, and ``telegram_posted`` reset to 0 so the change is re-posted.

This module imports only from ``starship_notam.data.connection``,
``starship_notam.core``, and the Python standard library.
"""

import hashlib
import json
from typing import Dict, List, Optional

from starship_notam.core.logging import logger
from starship_notam.data.connection import get_connection, init_db, utc_now_iso


def save_faa_license(record: Dict, db_path: Optional[str] = None) -> None:
    """Insert or update a FAA DRS launch license by ``doc_unique_id``.

    Serializes the ordered "Document Details" panel to JSON and computes a
    SHA-256 ``payload_hash`` over the change-relevant fields (including the
    content GUID, which changes when the document file is replaced) to detect
    changes. New licenses are inserted with ``telegram_posted = 0``; unchanged
    licenses are left untouched (preserving their Telegram posting state);
    changed licenses have all fields refreshed, ``updated_at`` bumped, and
    ``telegram_posted`` reset to 0 so they are re-posted.

    ``record`` is the normalized dict produced by
    :func:`starship_notam.parsers.faa_license_parser.parse_faa_license_summary`.
    A falsy/empty ``record`` (or one missing ``doc_unique_id``) is ignored.
    """
    if not record:
        logger.info("save_faa_license called with empty record; skipping")
        return

    doc_unique_id = str(record.get("doc_unique_id") or "").strip()
    if not doc_unique_id:
        logger.info(
            "save_faa_license: record missing doc_unique_id; skipping"
        )
        return

    init_db(db_path)

    details_json = json.dumps(
        record.get("details") or {}, sort_keys=True, ensure_ascii=False
    )

    payload = {
        "doc_unique_id": doc_unique_id,
        "content_guid": record.get("content_guid"),
        "doc_number": record.get("doc_number"),
        "doc_name": record.get("doc_name"),
        "doc_type_label": record.get("doc_type_label"),
        "status": record.get("status"),
        "revision_number": record.get("revision_number"),
        "issue_date": record.get("issue_date"),
        "expiration_date": record.get("expiration_date"),
        "details_json": details_json,
    }
    payload_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()

    conn = get_connection(db_path)
    try:
        cur = conn.cursor()

        cur.execute(
            "SELECT payload_hash FROM faa_licenses WHERE doc_unique_id = ?",
            (doc_unique_id,),
        )
        existing = cur.fetchone()

        if existing and existing["payload_hash"] == payload_hash:
            logger.info(
                "No changes detected for FAA DRS license '%s'; skipping DB update",
                doc_unique_id,
            )
            return

        now = utc_now_iso()

        if existing:
            logger.info(
                "Changes detected for FAA DRS license '%s'; updating record",
                doc_unique_id,
            )
            cur.execute(
                """
                UPDATE faa_licenses
                SET content_guid = ?,
                    doc_number = ?,
                    doc_name = ?,
                    doc_type_label = ?,
                    status = ?,
                    revision_number = ?,
                    issue_date = ?,
                    expiration_date = ?,
                    details_json = ?,
                    updated_at = ?,
                    payload_hash = ?,
                    telegram_posted = 0
                WHERE doc_unique_id = ?
                """,
                (
                    payload["content_guid"],
                    payload["doc_number"],
                    payload["doc_name"],
                    payload["doc_type_label"],
                    payload["status"],
                    payload["revision_number"],
                    payload["issue_date"],
                    payload["expiration_date"],
                    details_json,
                    now,
                    payload_hash,
                    doc_unique_id,
                ),
            )
        else:
            logger.info("Inserting new FAA DRS license '%s'", doc_unique_id)
            cur.execute(
                """
                INSERT INTO faa_licenses (
                    doc_unique_id,
                    content_guid,
                    doc_number,
                    doc_name,
                    doc_type_label,
                    status,
                    revision_number,
                    issue_date,
                    expiration_date,
                    details_json,
                    created_at,
                    updated_at,
                    payload_hash,
                    telegram_posted
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    doc_unique_id,
                    payload["content_guid"],
                    payload["doc_number"],
                    payload["doc_name"],
                    payload["doc_type_label"],
                    payload["status"],
                    payload["revision_number"],
                    payload["issue_date"],
                    payload["expiration_date"],
                    details_json,
                    now,
                    now,
                    payload_hash,
                ),
            )

        conn.commit()
    except Exception as e:
        logger.exception(f"Failed to save FAA DRS license to DB: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


def get_faa_licenses_needing_post(
    db_path: Optional[str] = None,
) -> List[Dict]:
    """Return FAA DRS licenses that have not yet been posted to Telegram.

    A license needs posting when ``telegram_posted = 0`` -- i.e. it is newly
    inserted or its tracked details changed since the last post. Each returned
    dict includes a ready-to-use ``details`` field (``details_json`` decoded
    back into an ordered dict) alongside the raw columns.
    """
    logger.info("Fetching FAA DRS licenses needing Telegram posting")
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id,
                   doc_unique_id,
                   content_guid,
                   doc_number,
                   doc_name,
                   doc_type_label,
                   status,
                   revision_number,
                   issue_date,
                   expiration_date,
                   details_json,
                   created_at,
                   updated_at,
                   payload_hash,
                   telegram_posted,
                   telegram_posted_at,
                   telegram_message_id
            FROM faa_licenses
            WHERE telegram_posted = 0
            ORDER BY created_at
            """
        )
        rows = cur.fetchall()
        result = []
        for r in rows:
            item = dict(r)
            try:
                item["details"] = json.loads(item.get("details_json") or "{}")
            except Exception:
                item["details"] = {}
            # A first-time insert has created_at == updated_at; anything else is
            # a change to an already-tracked license. Callers can use this to
            # word the notification ("new" vs "updated").
            item["is_new"] = item.get("created_at") == item.get("updated_at")
            result.append(item)
        logger.debug(
            "Found %d FAA DRS licenses needing Telegram posting", len(result)
        )
        return result
    finally:
        conn.close()


def mark_faa_license_posted(
    doc_unique_id, telegram_message_id, db_path: Optional[str] = None
) -> None:
    """Mark a FAA DRS license as posted to Telegram with its message ID."""
    logger.info(
        "Marking FAA DRS license '%s' as posted to Telegram with message ID %s",
        doc_unique_id,
        telegram_message_id,
    )
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE faa_licenses
            SET telegram_posted = 1,
                telegram_posted_at = ?,
                telegram_message_id = ?
            WHERE doc_unique_id = ?
            """,
            (utc_now_iso(), telegram_message_id, doc_unique_id),
        )
        conn.commit()
    except Exception as e:
        logger.exception(f"Failed to mark FAA DRS license as posted: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()
