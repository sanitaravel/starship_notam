"""FCC ELS application persistence — save, query, and update records.

Stores rows of the ``fcc_els_applications`` table through
:class:`~starship_notam.data.repository.PostedItemRepository`. A changed
application is posted again; applications whose detail page is still empty
are held back until it is filled in.

This module imports only from ``starship_notam.data`` and ``starship_notam.core``.
"""

import json
from typing import Dict, List, Optional

from starship_notam.data.repository import PostedItemRepository


def _is_empty_detail_json(value: Optional[str]) -> bool:
    """Return True when a ``detail_json`` value represents an empty detail.

    Single source of truth for the "empty detail" test used to gate
    post-eligibility in :meth:`FccElsApplicationRepository.after_load`. A value
    is empty when it is ``NULL``/``None``, empty/whitespace-only (all Python
    whitespace, including tabs and newlines), or the empty JSON object
    (``'{}'``, ignoring surrounding whitespace).
    """
    if value is None:
        return True
    stripped = value.strip()
    return stripped == "" or stripped == "{}"


class FccElsApplicationRepository(PostedItemRepository):
    table = "fcc_els_applications"
    key_col = "file_number"
    label = "FCC ELS application"
    columns = (
        "id",
        "file_number",
        "application_seq",
        "applicant_name",
        "call_sign",
        "receipt_date",
        "status",
        "status_date",
        "current_detail_url",
        "detail_json",
        "created_at",
        "updated_at",
        "payload_hash",
        "telegram_posted",
        "telegram_posted_at",
        "telegram_message_id",
    )
    repost_on_change = True

    def prepare(self, app: Dict):
        detail_json = json.dumps(
            app.get("detail") or {}, sort_keys=True, ensure_ascii=False
        )
        file_number = app.get("file_number")
        # The hash covers the key too (kept as-is: see repository.py).
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
        fields = {k: v for k, v in payload.items() if k != "file_number"}
        return file_number, fields, payload

    def after_load(self, rows: List[Dict]) -> List[Dict]:
        # Filtered in Python, not SQL: SQLite's TRIM only strips ASCII spaces,
        # so _is_empty_detail_json stays the one definition of "empty".
        return [r for r in rows if not _is_empty_detail_json(r["detail_json"])]


fcc_els_applications = FccElsApplicationRepository()
