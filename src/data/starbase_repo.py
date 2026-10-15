"""Starbase alert persistence — save, query, and update beach and road alerts.

Stores rows of the ``starbase_beach`` and ``starbase_road`` tables through
:class:`~src.data.repository.PostedItemRepository`. Alerts are
keyed by a hash of their window (and route, for roads). These tables call the
posted flag ``processed`` / ``processed_at`` and keep no message ID; an
updated closure is not posted again.

This module imports only from ``src.data`` and ``src.core``.
"""

import hashlib
import json
from typing import Dict

from src.data.repository import PostedItemRepository


def make_beach_key(start_utc, end_utc) -> str:
    """Return a stable SHA-256 key for a beach alert based on its window."""
    base = f"beach|{start_utc}|{end_utc}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def make_road_key(origin, destination, start_utc, end_utc) -> str:
    """Return a stable SHA-256 key for a road alert based on route and window."""
    base = f"road|{origin}|{destination}|{start_utc}|{end_utc}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


class _StarbaseAlertRepository(PostedItemRepository):
    key_col = "alert_key"
    posted_col = "processed"
    posted_at_col = "processed_at"
    message_id_col = None


class BeachAlertRepository(_StarbaseAlertRepository):
    table = "starbase_beach"
    label = "Beach alert"
    columns = ("alert_key", "description", "start_utc", "end_utc", "raw_date", "periods_json")

    def prepare(self, alert: Dict):
        fields = {
            "description": alert.get("description"),
            "is_closed": 1,
            "start_utc": alert.get("start_utc"),
            "end_utc": alert.get("end_utc"),
            "raw_date": alert.get("raw_date"),
            "periods_json": json.dumps(alert.get("periods") or [], ensure_ascii=False),
        }
        # The whole parsed alert is hashed (kept as-is: see repository.py).
        return make_beach_key(alert.get("start_utc"), alert.get("end_utc")), fields, alert


class RoadAlertRepository(_StarbaseAlertRepository):
    table = "starbase_road"
    label = "Road alert"
    columns = ("alert_key", "origin", "destination", "description", "start_utc", "end_utc")

    def prepare(self, alert: Dict):
        key = make_road_key(
            alert.get("origin"),
            alert.get("destination"),
            alert.get("start_utc"),
            alert.get("end_utc"),
        )
        fields = {
            "origin": alert.get("origin"),
            "destination": alert.get("destination"),
            "description": alert.get("description"),
            "start_utc": alert.get("start_utc"),
            "end_utc": alert.get("end_utc"),
            "raw_date": alert.get("raw_date"),
        }
        # The whole parsed alert is hashed (kept as-is: see repository.py).
        return key, fields, alert


beach_alerts = BeachAlertRepository()
road_alerts = RoadAlertRepository()
