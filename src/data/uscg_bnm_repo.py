"""USCG Broadcast Notice to Mariners persistence — save, query, and update.

Stores rows of the ``uscg_bnm_notices`` table through
:class:`~src.data.repository.PostedItemRepository`. Every Starship
space-operations bulletin the bot has kept is recorded, keyed by its kind and
BNM number (``SAFETY CGD-H BNM 0108-26``): a cancellation reuses the number
of the bulletin it cancels, so the number alone is not unique. A re-issued
notice (new launch date) gets a new number, so each bulletin is posted once,
when it first appears.

The hazard areas and windows are stored as JSON text and decoded again by
:meth:`UscgBnmRepository.after_load`.

This module imports only from ``src.data`` and ``src.core``.
"""

import json
from typing import Dict, List

from src.data.repository import PostedItemRepository

# Stored columns besides the notice_key key, in table order.
_FIELDS = (
    "bnm_id",
    "kind",
    "region",
    "title",
    "flight",
    "mission",
    "areas_json",
    "windows_json",
    "cancel_at",
    "cancels",
    "outcome",
    "published_at",
    "link",
)


class UscgBnmRepository(PostedItemRepository):
    table = "uscg_bnm_notices"
    key_col = "notice_key"
    label = "USCG BNM"
    columns = (
        "id",
        "notice_key",
        *_FIELDS,
        "created_at",
        "updated_at",
        "telegram_posted",
        "telegram_posted_at",
        "telegram_message_id",
    )
    order_by = "id"

    def prepare(self, record: Dict):
        notice_key = str((record or {}).get("notice_key") or "").strip()
        if not notice_key:
            return None
        fields = {name: record.get(name) for name in _FIELDS if not name.endswith("_json")}
        fields["areas_json"] = json.dumps(record.get("areas") or [])
        fields["windows_json"] = json.dumps(record.get("windows") or [])
        return notice_key, fields, fields

    def after_load(self, rows: List[Dict]) -> List[Dict]:
        for row in rows:
            row["areas"] = json.loads(row.pop("areas_json") or "[]")
            row["windows"] = json.loads(row.pop("windows_json") or "[]")
        return rows


uscg_bnm_notices = UscgBnmRepository()
