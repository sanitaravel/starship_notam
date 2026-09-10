"""NOTAM persistence functions — save, query, and update NOTAM records.

Provides CRUD-like operations for the ``notams`` table. Functions accept and
return plain Python dictionaries; no domain models are required.

This module imports only from ``starship_notam.data.connection``,
``starship_notam.core``, and the Python standard library.
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from starship_notam.core.config import DB_PATH
from starship_notam.core.logging import logger
from starship_notam.data.connection import get_connection, init_db, utc_now_iso


def save_notam(name: str, parsed: Dict, db_path: Optional[str] = None) -> None:
    """Insert or update a NOTAM by *name*.

    Stores structured fields extracted from the parsed dictionary and maintains
    ``created_at`` / ``updated_at`` timestamps.  Uses a SHA-256 hash of the
    JSON-serialised payload to detect changes; resets ``image_generated`` when
    the content has changed.
    """
    init_db(db_path)
    now = utc_now_iso()

    def _safe_get(k: str):
        return parsed.get(k) if isinstance(parsed, dict) else None

    col_values: Dict[str, Optional[str]] = {
        "A": _safe_get("A"),
        "B": _safe_get("B"),
        "C": _safe_get("C"),
        "D": _safe_get("D"),
        "E": _safe_get("E"),
        "F": _safe_get("F"),
        "G": _safe_get("G"),
    }

    q = parsed.get("Q") if isinstance(parsed, dict) else None
    if isinstance(q, dict):
        col_values.update(
            {
                "Q_location": q.get("location"),
                "Q_q_code": q.get("q_code"),
                "Q_traffic": q.get("traffic"),
                "Q_traffic_rule": q.get("traffic_rule"),
                "Q_lower": q.get("lower"),
                "Q_upper": q.get("upper"),
                "Q_coordinates": q.get("coordinates"),
                "Q_radius_nm": q.get("radius_nm"),
            }
        )
    else:
        col_values.update(
            {
                "Q_location": None,
                "Q_q_code": None,
                "Q_traffic": None,
                "Q_traffic_rule": None,
                "Q_lower": None,
                "Q_upper": None,
                "Q_coordinates": None,
                "Q_radius_nm": None,
            }
        )

    # Compute a stable hash of the parsed payload to detect changes
    try:
        parsed_json = json.dumps(parsed, sort_keys=True, ensure_ascii=False)
        parsed_hash = hashlib.sha256(parsed_json.encode("utf-8")).hexdigest()
    except Exception:
        parsed_hash = None

    conn = get_connection(db_path)
    try:
        cur = conn.cursor()

        cur.execute(
            "SELECT parsed_hash, A, B, C, D, E, F, G, "
            "Q_location, Q_q_code, Q_traffic, Q_traffic_rule, "
            "Q_lower, Q_upper, Q_coordinates, Q_radius_nm "
            "FROM notams WHERE name = ?",
            (name,),
        )
        existing = cur.fetchone()

        if existing:
            logger.info(f"Existing NOTAM found for {name}, checking for changes")
            existing_hash = existing["parsed_hash"]

            if (
                existing_hash is not None
                and parsed_hash is not None
                and existing_hash == parsed_hash
            ):
                logger.info(
                    f"No changes detected for {name} based on parsed_hash; skipping DB update"
                )
            else:
                logger.info(f"Changes detected for {name}; updating all fields")
                changed = False
                for k in list(col_values.keys()):
                    try:
                        existing_val = existing[k]
                    except Exception:
                        existing_val = None
                    new_val = col_values.get(k)
                    if (existing_val or "").strip() != (new_val or "").strip():
                        changed = True
                        break

                if changed or existing_hash != parsed_hash:
                    logger.info(
                        f"Effective changes detected for {name}; "
                        "updating structured fields and resetting image_generated"
                    )
                    update_cols = (
                        ["updated_at"]
                        + list(col_values.keys())
                        + ["parsed_hash", "image_generated", "image_generated_at"]
                    )
                    update_set = ", ".join(f"{c} = ?" for c in update_cols)
                    update_params = (
                        [now]
                        + [col_values[k] for k in col_values.keys()]
                        + [parsed_hash, 0, None, name]
                    )
                    cur.execute(
                        f"UPDATE notams SET {update_set} WHERE name = ?",
                        update_params,
                    )
                else:
                    logger.info(
                        f"No effective changes detected for {name}; "
                        "refreshing updated_at and structured fields"
                    )
                    update_cols = ["updated_at"] + list(col_values.keys())
                    update_set = ", ".join(f"{c} = ?" for c in update_cols)
                    update_params = (
                        [now] + [col_values[k] for k in col_values.keys()] + [name]
                    )
                    cur.execute(
                        f"UPDATE notams SET {update_set} WHERE name = ?",
                        update_params,
                    )
        else:
            logger.info(f"No existing NOTAM found for {name}; inserting new record")
            insert_cols = (
                ["name", "created_at", "updated_at"]
                + list(col_values.keys())
                + ["parsed_hash", "image_generated"]
            )
            placeholders = ",".join("?" for _ in insert_cols)
            insert_params = (
                [name, now, now]
                + [col_values[k] for k in col_values.keys()]
                + [parsed_hash, 0]
            )
            cur.execute(
                f"INSERT INTO notams ({','.join(insert_cols)}) VALUES ({placeholders})",
                insert_params,
            )

        conn.commit()
    except Exception as e:
        logger.exception(f"Failed to save NOTAM to DB: {e}")
        raise
    finally:
        conn.close()


def get_notams_needing_images(
    db_path: Optional[str] = None,
) -> List[Tuple[str, Dict]]:
    """Return list of ``(name, parsed_dict)`` where ``image_generated == 0``."""
    init_db(db_path)
    resolved_path = db_path or os.environ.get("NOTAM_DB_PATH") or DB_PATH
    if not Path(resolved_path).exists():
        return []
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT name, A, B, C, D, E, F, G, "
            "Q_location, Q_q_code, Q_traffic, Q_traffic_rule, "
            "Q_lower, Q_upper, Q_coordinates, Q_radius_nm "
            "FROM notams WHERE image_generated = 0 ORDER BY name"
        )
        rows = cur.fetchall()
        out: List[Tuple[str, Dict]] = []
        for r in rows:
            parsed: Dict = {}
            for k in ("A", "B", "C", "D", "E", "F", "G"):
                v = r[k]
                if v is not None:
                    parsed[k] = v
            q: Dict = {}
            q_map = {
                "location": r["Q_location"],
                "q_code": r["Q_q_code"],
                "traffic": r["Q_traffic"],
                "traffic_rule": r["Q_traffic_rule"],
                "lower": r["Q_lower"],
                "upper": r["Q_upper"],
                "coordinates": r["Q_coordinates"],
                "radius_nm": r["Q_radius_nm"],
            }
            for kk, vv in q_map.items():
                if vv is not None:
                    q[kk] = vv
            if q:
                parsed["Q"] = q
            out.append((r["name"], parsed))
        return out
    finally:
        conn.close()


def mark_image_generated(name: str, db_path: Optional[str] = None) -> None:
    """Mark a NOTAM as having had its image generated."""
    init_db(db_path)
    now = utc_now_iso()
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE notams SET image_generated = 1, image_generated_at = ? WHERE name = ?",
            (now, name),
        )
        conn.commit()
    finally:
        conn.close()


def load_all_notams(db_path: Optional[str] = None) -> List[Tuple[str, Dict]]:
    """Return list of ``(name, parsed_dict)`` for all NOTAMs ordered by name."""
    resolved_path = db_path or os.environ.get("NOTAM_DB_PATH") or DB_PATH
    if not Path(resolved_path).exists():
        return []
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT name, A, B, C, D, E, F, G, "
            "Q_location, Q_q_code, Q_traffic, Q_traffic_rule, "
            "Q_lower, Q_upper, Q_coordinates, Q_radius_nm "
            "FROM notams ORDER BY name"
        )
        rows = cur.fetchall()
        out: List[Tuple[str, Dict]] = []
        for r in rows:
            parsed: Dict = {}
            for k in ("A", "B", "C", "D", "E", "F", "G"):
                v = r[k]
                if v is not None:
                    parsed[k] = v
            q: Dict = {}
            q_map = {
                "location": r["Q_location"],
                "q_code": r["Q_q_code"],
                "traffic": r["Q_traffic"],
                "traffic_rule": r["Q_traffic_rule"],
                "lower": r["Q_lower"],
                "upper": r["Q_upper"],
                "coordinates": r["Q_coordinates"],
                "radius_nm": r["Q_radius_nm"],
            }
            for kk, vv in q_map.items():
                if vv is not None:
                    q[kk] = vv
            if q:
                parsed["Q"] = q
            out.append((r["name"], parsed))
        return out
    finally:
        conn.close()
