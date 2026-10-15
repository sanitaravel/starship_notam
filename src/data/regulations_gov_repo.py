"""Regulations.gov persistence — save, query, and update.

Stores rows of the ``regulations_gov_documents`` table through
:class:`~src.data.repository.PostedItemRepository`. Every FAA/USCG
Regulations.gov document matching the Starship search terms that the bot has
seen is recorded, keyed by the document id (e.g. ``FAA-2026-12808-0001``).
Only *new* documents are posted: the API bumps ``lastModifiedDate`` without
visible changes, so a later change to a known document is stored but does not
re-flag it for posting.

This module imports only from ``src.data`` and ``src.core``.
"""

from typing import Dict

from src.data.repository import PostedItemRepository

# Stored columns besides the document_id key, in table order.
_FIELDS = (
    "docket_id",
    "agency_id",
    "document_type",
    "subtype",
    "title",
    "fr_doc_num",
    "posted_date",
    "comment_end_date",
)


class RegulationsGovDocumentRepository(PostedItemRepository):
    table = "regulations_gov_documents"
    key_col = "document_id"
    label = "Regulations.gov document"
    columns = (
        "id",
        "document_id",
        *_FIELDS,
        "created_at",
        "updated_at",
        "telegram_posted",
        "telegram_posted_at",
        "telegram_message_id",
    )
    order_by = "id"

    def prepare(self, record: Dict):
        document_id = str((record or {}).get("document_id") or "").strip()
        if not document_id:
            return None
        fields = {name: record.get(name) for name in _FIELDS}
        # Only the stored fields are hashed (kept as-is: see repository.py).
        return document_id, fields, fields


regulations_gov_documents = RegulationsGovDocumentRepository()
