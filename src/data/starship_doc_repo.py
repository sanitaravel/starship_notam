"""Starship documentary persistence — save, query, and update.

Stores rows of the ``starship_documentaries`` table through
:class:`~src.data.repository.PostedItemRepository`. Every released episode of
SpaceX's Starship documentary series is recorded, keyed by its folder name
(e.g. ``StarshipDoc_Ep004``), and posted once, when it first appears.
:meth:`StarshipDocRepository.latest_episode` tells the fetcher where to
resume probing.

This module imports only from ``src.data`` and ``src.core``.
"""

from typing import Dict, Optional

from src.data.connection import get_connection, transaction
from src.data.repository import PostedItemRepository

_FIELDS = ("episode", "duration_seconds", "published_at", "master_url", "playlist_url")


class StarshipDocRepository(PostedItemRepository):
    table = "starship_documentaries"
    key_col = "episode_id"
    label = "Starship documentary episode"
    columns = ("id", "episode_id", *_FIELDS, "created_at", "updated_at",
               "telegram_posted", "telegram_posted_at", "telegram_message_id")
    order_by = "episode"

    def prepare(self, record: Dict):
        record = record or {}
        episode_id = str(record.get("episode_id") or "").strip()
        if not episode_id or not isinstance(record.get("episode"), int):
            return None
        fields = {name: record.get(name) for name in _FIELDS}
        return episode_id, fields, fields

    def latest_episode(self, db_path: Optional[str] = None) -> int:
        """Return the highest stored episode number, or 0 when none is stored."""
        with transaction(get_connection(db_path)) as cur:
            cur.execute(f"SELECT MAX(episode) AS n FROM {self.table}")
            row = cur.fetchone()
        return int(row["n"] or 0) if row else 0


starship_documentaries = StarshipDocRepository()
