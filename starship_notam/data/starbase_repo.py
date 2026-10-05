"""Starbase alert persistence functions — save, query, and update alerts.

Provides CRUD-like operations for the ``starbase_beach`` and ``starbase_road``
tables. Functions accept and return plain Python dictionaries; no domain models
are required.

This module imports only from ``starship_notam.data.connection``,
``starship_notam.core``, and the Python standard library.
"""

import hashlib
import json
from typing import Dict, List, Optional

from starship_notam.core.logging import logger
from starship_notam.data.connection import (
    get_connection,
    transaction,
    upsert,
    utc_now_iso,
)


def make_beach_key(start_utc, end_utc) -> str:
    """Return a stable SHA-256 key for a beach alert based on its window."""
    base = f"beach|{start_utc}|{end_utc}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def make_road_key(origin, destination, start_utc, end_utc) -> str:
    """Return a stable SHA-256 key for a road alert based on route and window."""
    base = f"road|{origin}|{destination}|{start_utc}|{end_utc}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def _save_alert(
    table: str, label: str, alert_key: str, alert: Dict, fields: Dict,
    db_path: Optional[str],
) -> None:
    """Upsert one Starbase alert row, keyed by *alert_key*.

    Unlike the other tables, no reset is applied on change: ``processed`` is
    left untouched, so an updated closure is not re-posted.
    """
    payload_hash = hashlib.sha256(
        json.dumps(alert, sort_keys=True).encode("utf-8")
    ).hexdigest()
    with transaction(get_connection(db_path)) as cur:
        result = upsert(cur, table, "alert_key", alert_key, fields, payload_hash)
    logger.info("%s alert: %s", label, result)


def save_beach_alert(alert: Dict, db_path: Optional[str] = None) -> None:
    """Insert or update a Starbase beach alert.

    Uses a SHA-256 hash of the JSON-serialised payload to detect changes and
    maintains ``created_at`` / ``updated_at`` timestamps. The alert is keyed by
    a stable hash of its start/end UTC window.
    """
    _save_alert(
        "starbase_beach",
        "Beach",
        make_beach_key(alert.get("start_utc"), alert.get("end_utc")),
        alert,
        {
            "description": alert.get("description"),
            "is_closed": 1,
            "start_utc": alert.get("start_utc"),
            "end_utc": alert.get("end_utc"),
            "raw_date": alert.get("raw_date"),
            "periods_json": json.dumps(alert.get("periods") or [], ensure_ascii=False),
        },
        db_path,
    )


def save_road_alert(alert: Dict, db_path: Optional[str] = None) -> None:
    """Insert or update a Starbase road-delay alert.

    Uses a SHA-256 hash of the JSON-serialised payload to detect changes and
    maintains ``created_at`` / ``updated_at`` timestamps. The alert is keyed by
    a stable hash of its route and start/end UTC window.
    """
    _save_alert(
        "starbase_road",
        "Road",
        make_road_key(
            alert.get("origin"),
            alert.get("destination"),
            alert.get("start_utc"),
            alert.get("end_utc"),
        ),
        alert,
        {
            "origin": alert.get("origin"),
            "destination": alert.get("destination"),
            "description": alert.get("description"),
            "start_utc": alert.get("start_utc"),
            "end_utc": alert.get("end_utc"),
            "raw_date": alert.get("raw_date"),
        },
        db_path,
    )


def _alerts_needing_post(table: str, columns: str, db_path: Optional[str]) -> List[Dict]:
    """Return the unprocessed rows of *table* (oldest first) as dicts."""
    with transaction(get_connection(db_path)) as cur:
        cur.execute(
            f"SELECT {columns} FROM {table} WHERE processed = 0 ORDER BY created_at"
        )
        rows = cur.fetchall()
    logger.debug("Found %d %s rows needing posting", len(rows), table)
    return [dict(r) for r in rows]


def get_beach_alerts_needing_post(db_path: Optional[str] = None) -> List[Dict]:
    """Return beach alerts that have not yet been processed/posted."""
    logger.info("Fetching beach alerts needing posting")
    return _alerts_needing_post(
        "starbase_beach",
        "alert_key, description, start_utc, end_utc, raw_date, periods_json",
        db_path,
    )


def get_road_alerts_needing_post(db_path: Optional[str] = None) -> List[Dict]:
    """Return road alerts that have not yet been processed/posted."""
    logger.info("Fetching road alerts needing posting")
    return _alerts_needing_post(
        "starbase_road",
        "alert_key, origin, destination, description, start_utc, end_utc",
        db_path,
    )


def _mark_processed(table: str, alert_key, db_path: Optional[str]) -> None:
    with transaction(get_connection(db_path)) as cur:
        cur.execute(
            f"UPDATE {table} SET processed = 1, processed_at = ? WHERE alert_key = ?",
            (utc_now_iso(), alert_key),
        )


def mark_beach_posted(alert_key, db_path: Optional[str] = None) -> None:
    """Mark a beach alert as processed/posted."""
    logger.info("Marking beach alert '%s' as posted", alert_key)
    _mark_processed("starbase_beach", alert_key, db_path)


def mark_road_posted(alert_key, db_path: Optional[str] = None) -> None:
    """Mark a road alert as processed/posted."""
    logger.info("Marking road alert '%s' as posted", alert_key)
    _mark_processed("starbase_road", alert_key, db_path)
