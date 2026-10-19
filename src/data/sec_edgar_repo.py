"""SEC EDGAR persistence — save, query, and update.

Stores rows of the ``sec_edgar_filings`` table through
:class:`~src.data.repository.PostedItemRepository`. Every SpaceX filing of a
posted form type that the bot has seen is recorded, keyed by the EDGAR
accession number (e.g. ``0001628280-26-056945``). A filing never changes once
accepted (corrections are new ``/A`` filings with their own number), so each
is posted once, when it first appears.

This module imports only from ``src.data`` and ``src.core``.
"""

from typing import Dict

from src.data.repository import PostedItemRepository

# Stored columns besides the accession_number key, in table order.
_FIELDS = (
    "form",
    "items",
    "filing_date",
    "report_date",
    "acceptance_datetime",
    "description",
    "document_url",
    "index_url",
)


class SecEdgarFilingRepository(PostedItemRepository):
    table = "sec_edgar_filings"
    key_col = "accession_number"
    label = "SEC EDGAR filing"
    columns = (
        "id",
        "accession_number",
        *_FIELDS,
        "created_at",
        "updated_at",
        "telegram_posted",
        "telegram_posted_at",
        "telegram_message_id",
    )
    order_by = "id"

    def prepare(self, record: Dict):
        accession_number = str((record or {}).get("accession_number") or "").strip()
        if not accession_number:
            return None
        fields = {name: record.get(name) for name in _FIELDS}
        # Only the stored fields are hashed (kept as-is: see repository.py).
        return accession_number, fields, fields


sec_edgar_filings = SecEdgarFilingRepository()
