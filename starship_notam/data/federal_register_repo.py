"""Federal Register persistence — save, query, and update.

Stores rows of the ``federal_register_documents`` table through
:class:`~starship_notam.data.repository.PostedItemRepository`. Every FAA
Federal Register document mentioning SpaceX that the bot has seen is
recorded, keyed by the document number (e.g. ``2026-20963``). Only *new*
documents are posted: a later change to an already-known document is stored
but does not re-flag it for posting.

This module imports only from ``starship_notam.data`` and ``starship_notam.core``.
"""

from typing import Dict, Iterable, List, Optional

from starship_notam.data.repository import PostedItemRepository

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


class FederalRegisterDocumentRepository(PostedItemRepository):
    table = "federal_register_documents"
    key_col = "document_number"
    label = "Federal Register document"
    columns = (
        "id",
        "document_number",
        *_FIELDS,
        "created_at",
        "updated_at",
        "telegram_posted",
        "telegram_posted_at",
        "telegram_message_id",
    )
    order_by = "id"

    def prepare(self, record: Dict):
        document_number = str((record or {}).get("document_number") or "").strip()
        if not document_number:
            return None
        fields = {name: record.get(name) for name in _FIELDS}
        # Only the stored fields are hashed (kept as-is: see repository.py).
        return document_number, fields, fields


_repo = FederalRegisterDocumentRepository()


def save_federal_register_document(record: Dict, db_path: Optional[str] = None) -> str:
    """Insert or update a Federal Register document by ``document_number``.

    Returns ``"inserted"``, ``"updated"``, ``"unchanged"`` or ``"skipped"``
    (record without ``document_number``).
    """
    return _repo.save(record, db_path)


def count_federal_register_documents(db_path: Optional[str] = None) -> int:
    """Return how many Federal Register documents the database has recorded."""
    return _repo.count(db_path)


def get_federal_register_documents_needing_post(db_path: Optional[str] = None) -> List[Dict]:
    """Return Federal Register documents not yet posted, in insertion order."""
    return _repo.needing_post(db_path)


def mark_federal_register_document_posted(
    document_number, telegram_message_id, db_path: Optional[str] = None
) -> None:
    """Mark a Federal Register document as posted with its message ID."""
    _repo.mark_posted(document_number, telegram_message_id, db_path)


def mark_federal_register_documents_posted(
    document_numbers: Iterable[str],
    telegram_message_id=None,
    db_path: Optional[str] = None,
) -> int:
    """Mark several Federal Register documents as posted; return rows changed.

    Rows already marked posted are left alone. Called with
    ``telegram_message_id=None`` to prefill the database with documents that
    should never be announced.
    """
    return _repo.mark_many_posted(document_numbers, telegram_message_id, db_path)
