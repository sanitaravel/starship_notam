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
from starship_notam.data.connection import (
    get_connection,
    transaction,
    upsert,
    utc_now_iso,
)

# Top-level NOTAM fields, stored in columns of the same name.
FIELD_COLS = ("A", "B", "C", "D", "E", "F", "G")

# Keys of the parsed "Q" dict -> the column each one is stored in.
Q_COLS = {
    "location": "Q_location",
    "q_code": "Q_q_code",
    "traffic": "Q_traffic",
    "traffic_rule": "Q_traffic_rule",
    "lower": "Q_lower",
    "upper": "Q_upper",
    "coordinates": "Q_coordinates",
    "radius_nm": "Q_radius_nm",
}

_SELECT_PARSED = (
    f"SELECT name, {', '.join(FIELD_COLS)}, {', '.join(Q_COLS.values())} FROM notams"
)


def _row_to_parsed(row) -> Dict:
    """Rebuild a parsed NOTAM dict from a ``notams`` row, omitting NULLs."""
    parsed: Dict = {k: row[k] for k in FIELD_COLS if row[k] is not None}
    q = {key: row[col] for key, col in Q_COLS.items() if row[col] is not None}
    if q:
        parsed["Q"] = q
    return parsed


def save_notam(name: str, parsed: Dict, db_path: Optional[str] = None) -> None:
    """Insert or update a NOTAM by *name*.

    Stores structured fields extracted from the parsed dictionary and maintains
    ``created_at`` / ``updated_at`` timestamps.  Uses a SHA-256 hash of the
    JSON-serialised payload to detect changes; resets ``image_generated`` when
    the content has changed.
    """
    parsed_dict = parsed if isinstance(parsed, dict) else {}
    q = parsed_dict.get("Q")
    if not isinstance(q, dict):
        q = {}

    fields: Dict[str, Optional[str]] = {k: parsed_dict.get(k) for k in FIELD_COLS}
    fields.update({col: q.get(key) for key, col in Q_COLS.items()})

    # Compute a stable hash of the parsed payload to detect changes
    try:
        parsed_json = json.dumps(parsed, sort_keys=True, ensure_ascii=False)
        parsed_hash = hashlib.sha256(parsed_json.encode("utf-8")).hexdigest()
    except Exception:
        parsed_hash = None

    with transaction(get_connection(db_path)) as cur:
        result = upsert(
            cur,
            "notams",
            "name",
            name,
            fields,
            parsed_hash,
            reset={"image_generated": 0, "image_generated_at": None},
            hash_col="parsed_hash",
        )
    logger.info("NOTAM %s: %s", name, result)


def _load_parsed(where: str, db_path: Optional[str]) -> List[Tuple[str, Dict]]:
    """Return ``(name, parsed_dict)`` for rows matching *where*, ordered by name.

    Returns an empty list when the database file does not exist, rather than
    creating it.
    """
    resolved_path = db_path or os.environ.get("NOTAM_DB_PATH") or DB_PATH
    if not Path(resolved_path).exists():
        return []
    with transaction(get_connection(db_path)) as cur:
        cur.execute(f"{_SELECT_PARSED} {where} ORDER BY name")
        rows = cur.fetchall()
    return [(r["name"], _row_to_parsed(r)) for r in rows]


def get_notams_needing_images(
    db_path: Optional[str] = None,
) -> List[Tuple[str, Dict]]:
    """Return list of ``(name, parsed_dict)`` where ``image_generated == 0``."""
    return _load_parsed("WHERE image_generated = 0", db_path)


def mark_image_generated(name: str, db_path: Optional[str] = None) -> None:
    """Mark a NOTAM as having had its image generated."""
    with transaction(get_connection(db_path)) as cur:
        cur.execute(
            "UPDATE notams SET image_generated = 1, image_generated_at = ? WHERE name = ?",
            (utc_now_iso(), name),
        )


def load_all_notams(db_path: Optional[str] = None) -> List[Tuple[str, Dict]]:
    """Return list of ``(name, parsed_dict)`` for all NOTAMs ordered by name."""
    return _load_parsed("", db_path)
