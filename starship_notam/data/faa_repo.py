"""FAA activity persistence — save, query, and update FAA planned activities.

Stores rows of the ``faa_activities`` table through
:class:`~starship_notam.data.repository.PostedItemRepository`. A changed
activity (e.g. a moved launch window) is posted again.

This module imports only from ``starship_notam.data`` and ``starship_notam.core``.
"""

from typing import Dict

from starship_notam.data.repository import PostedItemRepository


class FaaActivityRepository(PostedItemRepository):
    table = "faa_activities"
    key_col = "mission"
    label = "FAA activity"
    columns = ("mission", "primary_window", "backup_window")
    repost_on_change = True

    def prepare(self, activity: Dict):
        # The whole parsed activity is hashed (kept as-is: see repository.py).
        fields = {
            "primary_window": activity["primary_window"],
            "backup_window": activity["backup_window"],
        }
        return activity["mission"], fields, activity


faa_activities = FaaActivityRepository()
