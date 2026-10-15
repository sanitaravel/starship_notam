"""Data layer package — database schema, connections, and one repository per source.

Re-exports the public entry points. Items posted to Telegram are stored
through :class:`~starship_notam.data.repository.PostedItemRepository`
instances (``faa_activities.save(...)``, ``.needing_post()``,
``.mark_posted()``); NOTAMs have their own functions.
"""

from starship_notam.data.compass_repo import compass_files
from starship_notam.data.connection import get_connection
from starship_notam.data.faa_license_repo import faa_licenses
from starship_notam.data.faa_repo import faa_activities
from starship_notam.data.fcc_els_repo import fcc_els_applications
from starship_notam.data.federal_register_repo import federal_register_documents
from starship_notam.data.notam_repo import (
    get_notams_needing_images,
    load_all_notams,
    mark_image_generated,
    save_notam,
)
from starship_notam.data.schema import init_db
from starship_notam.data.starbase_repo import beach_alerts, road_alerts

__all__ = [
    "get_connection",
    "init_db",
    "save_notam",
    "get_notams_needing_images",
    "mark_image_generated",
    "load_all_notams",
    "faa_activities",
    "fcc_els_applications",
    "faa_licenses",
    "compass_files",
    "federal_register_documents",
    "beach_alerts",
    "road_alerts",
]
