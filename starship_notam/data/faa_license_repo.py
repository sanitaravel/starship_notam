"""FAA DRS launch-license persistence — save, query, and update.

Stores rows of the ``faa_licenses`` table through
:class:`~starship_notam.data.repository.PostedItemRepository`. The table
tracks a single FAA DRS launch (Vehicle Operator) license document and its
"Document Details" metadata. Any change to the tracked fields (including the
content GUID, which changes when the file is replaced) re-flags the license
for posting.

This module imports only from ``starship_notam.data`` and ``starship_notam.core``.
"""

import json
from typing import Dict, List, Optional

from starship_notam.data.repository import PostedItemRepository


class FaaLicenseRepository(PostedItemRepository):
    table = "faa_licenses"
    key_col = "doc_unique_id"
    label = "FAA DRS license"
    columns = (
        "id",
        "doc_unique_id",
        "content_guid",
        "doc_number",
        "doc_name",
        "doc_type_label",
        "status",
        "revision_number",
        "issue_date",
        "expiration_date",
        "details_json",
        "created_at",
        "updated_at",
        "payload_hash",
        "telegram_posted",
        "telegram_posted_at",
        "telegram_message_id",
    )
    repost_on_change = True

    def prepare(self, record: Dict):
        if not record:
            return None
        doc_unique_id = str(record.get("doc_unique_id") or "").strip()
        if not doc_unique_id:
            return None
        details_json = json.dumps(
            record.get("details") or {}, sort_keys=True, ensure_ascii=False
        )
        # The hash covers the key too (kept as-is: see repository.py).
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
        fields = {k: v for k, v in payload.items() if k != "doc_unique_id"}
        return doc_unique_id, fields, payload

    def after_load(self, rows: List[Dict]) -> List[Dict]:
        for item in rows:
            try:
                item["details"] = json.loads(item.get("details_json") or "{}")
            except Exception:
                item["details"] = {}
            # A first-time insert has created_at == updated_at; anything else
            # is a change to an already-tracked license. Callers use this to
            # word the notification ("new" vs "updated").
            item["is_new"] = item.get("created_at") == item.get("updated_at")
        return rows


_repo = FaaLicenseRepository()


def save_faa_license(record: Dict, db_path: Optional[str] = None) -> str:
    """Insert or update a FAA DRS launch license by ``doc_unique_id``.

    ``record`` is the normalized dict produced by
    :func:`starship_notam.parsers.faa_license_parser.parse_faa_license_summary`.
    A falsy/empty ``record`` (or one missing ``doc_unique_id``) is skipped.
    """
    return _repo.save(record, db_path)


def get_faa_licenses_needing_post(
    db_path: Optional[str] = None,
) -> List[Dict]:
    """Return FAA DRS licenses that have not yet been posted to Telegram.

    Each returned dict includes ``details`` (``details_json`` decoded) and
    ``is_new`` (False when the license changed since it was first stored).
    """
    return _repo.needing_post(db_path)


def mark_faa_license_posted(
    doc_unique_id, telegram_message_id, db_path: Optional[str] = None
) -> None:
    """Mark a FAA DRS license as posted to Telegram with its message ID."""
    _repo.mark_posted(doc_unique_id, telegram_message_id, db_path)
