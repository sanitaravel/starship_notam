"""Data layer package — SQLite database initialization, connection management, and repositories.

Re-exports public functions from submodules for convenient access.
"""

from starship_notam.data.connection import get_connection, init_db
from starship_notam.data.notam_repo import (
    get_notams_needing_images,
    load_all_notams,
    mark_image_generated,
    save_notam,
)

__all__ = [
    "get_connection",
    "init_db",
    "save_notam",
    "get_notams_needing_images",
    "mark_image_generated",
    "load_all_notams",
]
