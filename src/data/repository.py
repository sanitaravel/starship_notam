"""Base class for tables of items that are posted to Telegram.

FAA activities, FCC ELS applications, FAA licenses, COMPASS files, Federal
Register documents and Starbase alerts are stored the same way: one row per
item keyed by a source identifier, a SHA-256 ``payload_hash`` for change
detection, and a "posted" flag with its timestamp (``telegram_posted`` /
``telegram_posted_at``, plus ``telegram_message_id``; the Starbase tables
call them ``processed`` / ``processed_at`` and keep no message ID).
Subclasses describe their table and implement :meth:`prepare`; the base class
does the upsert, the "needing post" query and the marking.

Each subclass decides exactly what is hashed. Changing that for an existing
source would make every stored row look changed once, and sources with
``repost_on_change`` would post everything again (see
``tests/unit/test_data/test_repository_hashes.py``).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.core.logging import logger
from src.data.connection import (
    get_connection,
    transaction,
    upsert,
    utc_now_iso,
)


def payload_hash(payload: Any) -> str:
    """SHA-256 of *payload* serialized as JSON with sorted keys."""
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


class PostedItemRepository:
    """Store items found by a fetcher and track which were posted to Telegram."""

    #: Table name.
    table: str
    #: Column holding the item's unique source identifier.
    key_col: str
    #: Item name used in log lines, e.g. "COMPASS file".
    label: str
    #: Columns returned by :meth:`needing_post`, in order.
    columns: Tuple[str, ...]
    #: Order of :meth:`needing_post` rows.
    order_by: str = "created_at"
    #: Post a stored item again when its content changes.
    repost_on_change: bool = False
    #: Flag set once the item is posted, and when that happened.
    posted_col: str = "telegram_posted"
    posted_at_col: str = "telegram_posted_at"
    #: Column for the Telegram message ID(s), or None if the table has none.
    message_id_col: Optional[str] = "telegram_message_id"

    def prepare(self, record: Dict) -> Optional[Tuple[Any, Dict[str, Any], Any]]:
        """Return ``(key, fields, hashed)`` for *record*, or None to skip it.

        ``fields`` are the stored columns besides the key; ``hashed`` is the
        object whose JSON serialization is hashed for change detection.
        """
        raise NotImplementedError

    def after_load(self, rows: List[Dict]) -> List[Dict]:
        """Adjust the rows returned by :meth:`needing_post`; unchanged by default."""
        return rows

    def save(self, record: Dict, db_path: Optional[str] = None) -> str:
        """Insert or update *record*.

        Returns ``"inserted"``, ``"updated"``, ``"unchanged"`` or
        ``"skipped"`` (when :meth:`prepare` rejects the record). An updated row
        is re-flagged for posting only when :attr:`repost_on_change` is set.
        """
        prepared = self.prepare(record)
        if prepared is None:
            logger.info("Skipping %s without %s: %s", self.label, self.key_col, record)
            return "skipped"
        key, fields, hashed = prepared

        reset = {self.posted_col: 0} if self.repost_on_change else None
        with transaction(get_connection(db_path)) as cur:
            result = upsert(
                cur, self.table, self.key_col, key, fields, payload_hash(hashed), reset=reset
            )
        logger.info("%s '%s': %s", self.label, key, result)
        return result

    def count(self, db_path: Optional[str] = None) -> int:
        """Return how many items the table holds."""
        with transaction(get_connection(db_path)) as cur:
            cur.execute(f"SELECT COUNT(*) AS n FROM {self.table}")
            return cur.fetchone()["n"]

    def known(self, keys: Iterable, db_path: Optional[str] = None) -> set:
        """Return the subset of *keys* the table holds, posted or not."""
        keys = list(keys)
        if not keys:
            return set()
        placeholders = ", ".join("?" for _ in keys)
        with transaction(get_connection(db_path)) as cur:
            cur.execute(
                f"SELECT {self.key_col} FROM {self.table} "
                f"WHERE {self.key_col} IN ({placeholders})",
                keys,
            )
            return {r[self.key_col] for r in cur.fetchall()}

    def needing_post(self, db_path: Optional[str] = None) -> List[Dict]:
        """Return the items not yet posted to Telegram, oldest first."""
        logger.info("Fetching %s rows needing Telegram posting", self.table)
        with transaction(get_connection(db_path)) as cur:
            cur.execute(
                f"SELECT {', '.join(self.columns)} FROM {self.table} "
                f"WHERE {self.posted_col} = 0 ORDER BY {self.order_by}"
            )
            rows = [dict(r) for r in cur.fetchall()]
        result = self.after_load(rows)
        logger.debug("Found %d %s rows needing Telegram posting", len(result), self.table)
        return result

    def mark_posted(self, key, telegram_message_id, db_path: Optional[str] = None) -> None:
        """Mark one item as posted with the Telegram message ID(s)."""
        logger.info(
            "Marking %s '%s' as posted to Telegram with message ID %s",
            self.label,
            key,
            telegram_message_id,
        )
        self.mark_many_posted([key], telegram_message_id, db_path)

    def mark_many_posted(
        self,
        keys: Iterable,
        telegram_message_id=None,
        db_path: Optional[str] = None,
    ) -> int:
        """Mark several items as posted; return how many rows changed.

        Rows already marked posted are left alone, so their recorded message
        IDs are kept. Called with ``telegram_message_id=None`` to prefill the
        database with items that should never be announced. The message ID is
        dropped for tables without :attr:`message_id_col`.
        """
        values = {self.posted_col: 1, self.posted_at_col: utc_now_iso()}
        if self.message_id_col:
            values[self.message_id_col] = telegram_message_id
        set_clause = ", ".join(f"{col} = ?" for col in values)
        changed = 0
        with transaction(get_connection(db_path)) as cur:
            for key in keys:
                cur.execute(
                    f"UPDATE {self.table} SET {set_clause} "
                    f"WHERE {self.key_col} = ? AND {self.posted_col} = 0",
                    (*values.values(), key),
                )
                changed += cur.rowcount
        return changed
