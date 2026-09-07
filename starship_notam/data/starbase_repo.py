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
from starship_notam.data.connection import get_connection, init_db, utc_now_iso


def make_beach_key(start_utc, end_utc) -> str:
    """Return a stable SHA-256 key for a beach alert based on its window."""
    base = f"beach|{start_utc}|{end_utc}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def make_road_key(origin, destination, start_utc, end_utc) -> str:
    """Return a stable SHA-256 key for a road alert based on route and window."""
    base = f"road|{origin}|{destination}|{start_utc}|{end_utc}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def save_beach_alert(alert: Dict, db_path: Optional[str] = None) -> None:
    """Insert or update a Starbase beach alert.

    Uses a SHA-256 hash of the JSON-serialised payload to detect changes and
    maintains ``created_at`` / ``updated_at`` timestamps. The alert is keyed by
    a stable hash of its start/end UTC window.
    """
    init_db(db_path)

    now = utc_now_iso()

    payload_hash = hashlib.sha256(
        json.dumps(alert, sort_keys=True).encode("utf-8")
    ).hexdigest()

    periods_json = json.dumps(alert.get("periods") or [], ensure_ascii=False)

    alert_key = make_beach_key(
        alert.get("start_utc"),
        alert.get("end_utc"),
    )

    conn = get_connection(db_path)
    try:
        cur = conn.cursor()

        cur.execute(
            "SELECT payload_hash FROM starbase_beach WHERE alert_key = ?",
            (alert_key,),
        )
        existing = cur.fetchone()

        if existing and existing["payload_hash"] == payload_hash:
            logger.info("No changes detected for beach alert; skipping DB update")
            return

        if existing:
            logger.info("Changes detected for beach alert; updating record")
            cur.execute(
                """
                UPDATE starbase_beach
                SET description = ?,
                    is_closed = ?,
                    start_utc = ?,
                    end_utc = ?,
                    raw_date = ?,
                    periods_json = ?,
                    updated_at = ?,
                    payload_hash = ?
                WHERE alert_key = ?
                """,
                (
                    alert.get("description"),
                    1,
                    alert.get("start_utc"),
                    alert.get("end_utc"),
                    alert.get("raw_date"),
                    periods_json,
                    now,
                    payload_hash,
                    alert_key,
                ),
            )
        else:
            logger.info("Inserting new beach alert record")
            cur.execute(
                """
                INSERT INTO starbase_beach (
                    alert_key,
                    description,
                    is_closed,
                    start_utc,
                    end_utc,
                    raw_date,
                    periods_json,
                    created_at,
                    updated_at,
                    payload_hash
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert_key,
                    alert.get("description"),
                    1,
                    alert.get("start_utc"),
                    alert.get("end_utc"),
                    alert.get("raw_date"),
                    periods_json,
                    now,
                    now,
                    payload_hash,
                ),
            )

        conn.commit()
    except Exception as e:
        logger.exception(f"Failed to save beach alert to DB: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


def save_road_alert(alert: Dict, db_path: Optional[str] = None) -> None:
    """Insert or update a Starbase road-delay alert.

    Uses a SHA-256 hash of the JSON-serialised payload to detect changes and
    maintains ``created_at`` / ``updated_at`` timestamps. The alert is keyed by
    a stable hash of its route and start/end UTC window.
    """
    init_db(db_path)

    now = utc_now_iso()

    payload_hash = hashlib.sha256(
        json.dumps(alert, sort_keys=True).encode("utf-8")
    ).hexdigest()

    alert_key = make_road_key(
        alert.get("origin"),
        alert.get("destination"),
        alert.get("start_utc"),
        alert.get("end_utc"),
    )

    conn = get_connection(db_path)
    try:
        cur = conn.cursor()

        cur.execute(
            "SELECT payload_hash FROM starbase_road WHERE alert_key = ?",
            (alert_key,),
        )
        existing = cur.fetchone()

        if existing and existing["payload_hash"] == payload_hash:
            logger.info("No changes detected for road alert; skipping DB update")
            return

        if existing:
            logger.info("Changes detected for road alert; updating record")
            cur.execute(
                """
                UPDATE starbase_road
                SET origin = ?,
                    destination = ?,
                    description = ?,
                    start_utc = ?,
                    end_utc = ?,
                    raw_date = ?,
                    updated_at = ?,
                    payload_hash = ?
                WHERE alert_key = ?
                """,
                (
                    alert.get("origin"),
                    alert.get("destination"),
                    alert.get("description"),
                    alert.get("start_utc"),
                    alert.get("end_utc"),
                    alert.get("raw_date"),
                    now,
                    payload_hash,
                    alert_key,
                ),
            )
        else:
            logger.info("Inserting new road alert record")
            cur.execute(
                """
                INSERT INTO starbase_road (
                    alert_key,
                    origin,
                    destination,
                    description,
                    start_utc,
                    end_utc,
                    raw_date,
                    created_at,
                    updated_at,
                    payload_hash
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert_key,
                    alert.get("origin"),
                    alert.get("destination"),
                    alert.get("description"),
                    alert.get("start_utc"),
                    alert.get("end_utc"),
                    alert.get("raw_date"),
                    now,
                    now,
                    payload_hash,
                ),
            )

        conn.commit()
    except Exception as e:
        logger.exception(f"Failed to save road alert to DB: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


def get_beach_alerts_needing_post(db_path: Optional[str] = None) -> List[Dict]:
    """Return beach alerts that have not yet been processed/posted."""
    logger.info("Fetching beach alerts needing posting")
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT alert_key, description, start_utc, end_utc, raw_date, periods_json
            FROM starbase_beach
            WHERE processed = 0
            ORDER BY created_at
            """
        )
        rows = cur.fetchall()
        logger.debug("Found %d beach alerts needing posting", len(rows))
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_road_alerts_needing_post(db_path: Optional[str] = None) -> List[Dict]:
    """Return road alerts that have not yet been processed/posted."""
    logger.info("Fetching road alerts needing posting")
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT alert_key, origin, destination, description, start_utc, end_utc
            FROM starbase_road
            WHERE processed = 0
            ORDER BY created_at
            """
        )
        rows = cur.fetchall()
        logger.debug("Found %d road alerts needing posting", len(rows))
        return [dict(r) for r in rows]
    finally:
        conn.close()


def mark_beach_posted(alert_key, db_path: Optional[str] = None) -> None:
    """Mark a beach alert as processed/posted."""
    logger.info("Marking beach alert '%s' as posted", alert_key)
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE starbase_beach
            SET processed = 1,
                processed_at = ?
            WHERE alert_key = ?
            """,
            (utc_now_iso(), alert_key),
        )
        conn.commit()
    finally:
        conn.close()


def mark_road_posted(alert_key, db_path: Optional[str] = None) -> None:
    """Mark a road alert as processed/posted."""
    logger.info("Marking road alert '%s' as posted", alert_key)
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE starbase_road
            SET processed = 1,
                processed_at = ?
            WHERE alert_key = ?
            """,
            (utc_now_iso(), alert_key),
        )
        conn.commit()
    finally:
        conn.close()
