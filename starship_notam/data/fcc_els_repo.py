"""FCC ELS application persistence functions — save, query, and update records.

Provides CRUD-like operations for the ``fcc_els_applications`` table. Functions
accept and return plain Python dictionaries; no domain models are required.

This module imports only from ``starship_notam.data.connection``,
``starship_notam.core``, and the Python standard library.
"""

import hashlib
import json
from typing import Dict, List, Optional

from starship_notam.core.logging import logger
from starship_notam.data.connection import get_connection, init_db, utc_now_iso


def save_fcc_els_application(app: Dict, db_path: Optional[str] = None) -> None:
    """Insert or update an FCC ELS application by *file_number*.

    Serialises the application's detail field set to JSON and computes a
    deterministic SHA-256 payload hash to detect changes. New applications are
    inserted with ``telegram_posted = 0``; unchanged applications are left
    untouched (including their Telegram posting state); changed applications
    have all fields refreshed, ``updated_at`` bumped, and ``telegram_posted``
    reset to 0 so they are re-posted.
    """
    init_db(db_path)

    detail_json = json.dumps(
        app.get("detail") or {}, sort_keys=True, ensure_ascii=False
    )

    file_number = app.get("file_number")

    payload = {
        "file_number": file_number,
        "application_seq": app.get("application_seq"),
        "applicant_name": app.get("applicant_name"),
        "call_sign": app.get("call_sign"),
        "receipt_date": app.get("receipt_date"),
        "status": app.get("status"),
        "status_date": app.get("status_date"),
        "current_detail_url": app.get("current_detail_url"),
        "detail_json": detail_json,
    }
    payload_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()

    conn = get_connection(db_path)
    try:
        cur = conn.cursor()

        cur.execute(
            "SELECT payload_hash FROM fcc_els_applications WHERE file_number = ?",
            (file_number,),
        )
        existing = cur.fetchone()

        if existing and existing["payload_hash"] == payload_hash:
            logger.info(
                "No changes detected for FCC ELS application '%s'; skipping DB update",
                file_number,
            )
            return

        now = utc_now_iso()

        if existing:
            logger.info(
                "Changes detected for FCC ELS application '%s'; updating record",
                file_number,
            )
            cur.execute(
                """
                UPDATE fcc_els_applications
                SET application_seq = ?,
                    applicant_name = ?,
                    call_sign = ?,
                    receipt_date = ?,
                    status = ?,
                    status_date = ?,
                    current_detail_url = ?,
                    detail_json = ?,
                    updated_at = ?,
                    payload_hash = ?,
                    telegram_posted = 0
                WHERE file_number = ?
                """,
                (
                    payload["application_seq"],
                    payload["applicant_name"],
                    payload["call_sign"],
                    payload["receipt_date"],
                    payload["status"],
                    payload["status_date"],
                    payload["current_detail_url"],
                    detail_json,
                    now,
                    payload_hash,
                    file_number,
                ),
            )
        else:
            logger.info(
                "Inserting new FCC ELS application '%s'", file_number
            )
            cur.execute(
                """
                INSERT INTO fcc_els_applications (
                    file_number,
                    application_seq,
                    applicant_name,
                    call_sign,
                    receipt_date,
                    status,
                    status_date,
                    current_detail_url,
                    detail_json,
                    created_at,
                    updated_at,
                    payload_hash,
                    telegram_posted
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    file_number,
                    payload["application_seq"],
                    payload["applicant_name"],
                    payload["call_sign"],
                    payload["receipt_date"],
                    payload["status"],
                    payload["status_date"],
                    payload["current_detail_url"],
                    detail_json,
                    now,
                    now,
                    payload_hash,
                ),
            )

        conn.commit()
    except Exception as e:
        logger.exception(f"Failed to save FCC ELS application to DB: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


def get_fcc_els_applications_needing_post(
    db_path: Optional[str] = None,
) -> List[Dict]:
    """Return FCC ELS applications that have not yet been posted to Telegram."""
    logger.info("Fetching FCC ELS applications needing Telegram posting")
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id,
                   file_number,
                   application_seq,
                   applicant_name,
                   call_sign,
                   receipt_date,
                   status,
                   status_date,
                   current_detail_url,
                   detail_json,
                   created_at,
                   updated_at,
                   payload_hash,
                   telegram_posted,
                   telegram_posted_at,
                   telegram_message_id
            FROM fcc_els_applications
            WHERE telegram_posted = 0
            ORDER BY created_at
            """
        )
        rows = cur.fetchall()
        logger.debug(
            "Found %d FCC ELS applications needing Telegram posting", len(rows)
        )
        return [dict(r) for r in rows]
    finally:
        conn.close()


def mark_fcc_els_application_posted(
    file_number, telegram_message_id, db_path: Optional[str] = None
) -> None:
    """Mark an FCC ELS application as posted to Telegram with its message ID."""
    logger.info(
        "Marking FCC ELS application '%s' as posted to Telegram with message ID %s",
        file_number,
        telegram_message_id,
    )
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE fcc_els_applications
            SET telegram_posted = 1,
                telegram_posted_at = ?,
                telegram_message_id = ?
            WHERE file_number = ?
            """,
            (utc_now_iso(), telegram_message_id, file_number),
        )
        conn.commit()
    except Exception as e:
        logger.exception(
            f"Failed to mark FCC ELS application as posted: {e}"
        )
        conn.rollback()
        raise
    finally:
        conn.close()
