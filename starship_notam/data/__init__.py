"""Data layer package — SQLite database initialization, connection management, and repositories.

Re-exports public functions from submodules for convenient access.
"""

from starship_notam.data.connection import get_connection, init_db
from starship_notam.data.faa_repo import (
    get_faa_activities_needing_post,
    mark_faa_activity_posted,
    save_faa_activity,
)
from starship_notam.data.fcc_els_repo import (
    get_fcc_els_applications_needing_post,
    mark_fcc_els_application_posted,
    save_fcc_els_application,
)
from starship_notam.data.notam_repo import (
    get_notams_needing_images,
    load_all_notams,
    mark_image_generated,
    save_notam,
)
from starship_notam.data.starbase_repo import (
    get_beach_alerts_needing_post,
    get_road_alerts_needing_post,
    mark_beach_posted,
    mark_road_posted,
    save_beach_alert,
    save_road_alert,
)

__all__ = [
    "get_connection",
    "init_db",
    "save_notam",
    "get_notams_needing_images",
    "mark_image_generated",
    "load_all_notams",
    "save_faa_activity",
    "get_faa_activities_needing_post",
    "mark_faa_activity_posted",
    "save_fcc_els_application",
    "get_fcc_els_applications_needing_post",
    "mark_fcc_els_application_posted",
    "save_beach_alert",
    "save_road_alert",
    "get_beach_alerts_needing_post",
    "get_road_alerts_needing_post",
    "mark_beach_posted",
    "mark_road_posted",
]
