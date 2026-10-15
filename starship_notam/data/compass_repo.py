"""COMPASS Master Slide Deck persistence — save, query, and update.

Stores rows of the ``compass_files`` table through
:class:`~starship_notam.data.repository.PostedItemRepository`. Every file seen
in the COMPASS "Master Slide Deck" list is recorded, keyed by the site's
``fileuuid``. Only *new* files are posted: a changed name or upload time on an
already-known file is stored but does not re-flag it for posting.

This module imports only from ``starship_notam.data`` and ``starship_notam.core``.
"""

from typing import Dict, Iterable, List, Optional

from starship_notam.data.repository import PostedItemRepository


class CompassFileRepository(PostedItemRepository):
    table = "compass_files"
    key_col = "file_uuid"
    label = "COMPASS file"
    columns = (
        "id",
        "file_uuid",
        "filename",
        "uploaded_at",
        "created_at",
        "updated_at",
        "telegram_posted",
        "telegram_posted_at",
        "telegram_message_id",
    )
    order_by = "id"

    def prepare(self, record: Dict):
        file_uuid = str((record or {}).get("file_uuid") or "").strip()
        if not file_uuid:
            return None
        fields = {
            "filename": record.get("filename"),
            "uploaded_at": record.get("uploaded_at"),
        }
        # Only the stored fields are hashed (kept as-is: see repository.py).
        return file_uuid, fields, fields


_repo = CompassFileRepository()


def save_compass_file(record: Dict, db_path: Optional[str] = None) -> str:
    """Insert or update a COMPASS file by ``file_uuid``.

    Returns ``"inserted"``, ``"updated"``, ``"unchanged"`` or ``"skipped"``
    (record without ``file_uuid``).
    """
    return _repo.save(record, db_path)


def count_compass_files(db_path: Optional[str] = None) -> int:
    """Return how many COMPASS files the database has recorded."""
    return _repo.count(db_path)


def get_compass_files_needing_post(db_path: Optional[str] = None) -> List[Dict]:
    """Return COMPASS files not yet posted to Telegram, in insertion order."""
    return _repo.needing_post(db_path)


def mark_compass_file_posted(
    file_uuid, telegram_message_id, db_path: Optional[str] = None
) -> None:
    """Mark a COMPASS file as posted to Telegram with its message ID."""
    _repo.mark_posted(file_uuid, telegram_message_id, db_path)


def mark_compass_files_posted(
    file_uuids: Iterable[str],
    telegram_message_id=None,
    db_path: Optional[str] = None,
) -> int:
    """Mark several COMPASS files as posted; return how many rows changed.

    Rows already marked posted are left alone. Called with
    ``telegram_message_id=None`` to prefill the database with files that
    should never be announced.
    """
    return _repo.mark_many_posted(file_uuids, telegram_message_id, db_path)
