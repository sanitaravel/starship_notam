"""Federal Register persistence — save, query, and update.

Stores rows of the ``federal_register_documents`` table through
:class:`~src.data.repository.PostedItemRepository`. Every FAA
Federal Register document mentioning SpaceX that the bot has seen is
recorded, keyed by the document number (e.g. ``2026-20963``). Only *new*
documents are posted: a later change to an already-known document is stored
but does not re-flag it for posting.

This module imports only from ``src.data`` and ``src.core``.
"""

from typing import Dict

from src.data.repository import PostedItemRepository

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


federal_register_documents = FederalRegisterDocumentRepository()
