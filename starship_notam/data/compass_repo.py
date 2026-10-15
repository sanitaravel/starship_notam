"""COMPASS Master Slide Deck persistence — save, query, and update.

Stores rows of the ``compass_files`` table through
:class:`~starship_notam.data.repository.PostedItemRepository`. Every file seen
in the COMPASS "Master Slide Deck" list is recorded, keyed by the site's
``fileuuid``. Only *new* files are posted: a changed name or upload time on an
already-known file is stored but does not re-flag it for posting.

This module imports only from ``starship_notam.data`` and ``starship_notam.core``.
"""

from typing import Dict

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


compass_files = CompassFileRepository()
