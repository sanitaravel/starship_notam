"""Federal Register persistence functions — save, query, and update.

Provides operations for the ``federal_register_documents`` table, which
records every FAA Federal Register document mentioning SpaceX that the bot has
seen, keyed by the document number (e.g. ``2026-20963``). Only *new*
documents are posted: a later change to an already-known document is stored
but does not re-flag it for posting.

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

# Stored columns besides the document_number key, in table order.
_FIELDS = (
    "title",
    "doc_type",
    "abstract",
    "publication_date",
    "comments_close_on",
    "html_url",
    "pdf_url",
)


def save_federal_register_document(record: Dict, db_path: Optional[str] = None) -> str:
    """Insert or update a Federal Register document by ``document_number``.

    New documents are inserted with ``telegram_posted = 0``; existing ones keep
    their posting state. Returns ``"inserted"``, ``"updated"``,
    ``"unchanged"`` or ``"skipped"`` (record without ``document_number``).
    """
    document_number = str((record or {}).get("document_number") or "").strip()
    if not document_number:
        logger.info("save_federal_register_document: record missing document_number; skipping")
        return "skipped"

    fields = {name: record.get(name) for name in _FIELDS}
    payload_hash = hashlib.sha256(
        json.dumps(fields, sort_keys=True).encode("utf-8")
    ).hexdigest()

    with transaction(get_connection(db_path)) as cur:
        result = upsert(
            cur,
            "federal_register_documents",
            "document_number",
            document_number,
            fields,
            payload_hash,
        )
    logger.info("Federal Register document '%s': %s", document_number, result)
    return result


def get_federal_register_documents_needing_post(db_path: Optional[str] = None) -> List[Dict]:
    """Return Federal Register documents not yet posted, in insertion order."""
    logger.info("Fetching Federal Register documents needing Telegram posting")
    with transaction(get_connection(db_path)) as cur:
        cur.execute(
            f"""
            SELECT id,
                   document_number,
                   {", ".join(_FIELDS)},
                   created_at,
                   updated_at,
                   telegram_posted,
                   telegram_posted_at,
                   telegram_message_id
            FROM federal_register_documents
            WHERE telegram_posted = 0
            ORDER BY id
            """
        )
        return [dict(r) for r in cur.fetchall()]


def mark_federal_register_document_posted(
    document_number, telegram_message_id, db_path: Optional[str] = None
) -> None:
    """Mark a Federal Register document as posted with its message ID."""
    logger.info(
        "Marking Federal Register document '%s' as posted to Telegram with message ID %s",
        document_number,
        telegram_message_id,
    )
    mark_federal_register_documents_posted([document_number], telegram_message_id, db_path)


def mark_federal_register_documents_posted(
    document_numbers: Iterable[str],
    telegram_message_id=None,
    db_path: Optional[str] = None,
) -> int:
    """Mark several Federal Register documents as posted; return rows changed.

    Rows already marked posted are left alone, so their recorded message IDs
    are kept. Called with ``telegram_message_id=None`` for documents that
    should never be announced (already too old when first seen).
    """
    now = utc_now_iso()
    changed = 0
    with transaction(get_connection(db_path)) as cur:
        for document_number in document_numbers:
            cur.execute(
                """
                UPDATE federal_register_documents
                SET telegram_posted = 1,
                    telegram_posted_at = ?,
                    telegram_message_id = ?
                WHERE document_number = ? AND telegram_posted = 0
                """,
                (now, telegram_message_id, document_number),
            )
            changed += cur.rowcount
    return changed
