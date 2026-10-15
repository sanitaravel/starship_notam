"""FAA activity persistence — save, query, and update FAA planned activities.

Stores rows of the ``faa_activities`` table through
:class:`~starship_notam.data.repository.PostedItemRepository`. A changed
activity (e.g. a moved launch window) is posted again.

This module imports only from ``starship_notam.data`` and ``starship_notam.core``.
"""

from typing import Dict, List, Optional

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


_repo = FaaActivityRepository()


def save_faa_activity(activity: Dict, db_path: Optional[str] = None) -> str:
    """Insert or update an FAA activity by *mission*; a change re-flags it for posting."""
    return _repo.save(activity, db_path)


def get_faa_activities_needing_post(db_path: Optional[str] = None) -> List[Dict]:
    """Return FAA activities that have not yet been posted to Telegram."""
    return _repo.needing_post(db_path)


def mark_faa_activity_posted(mission, telegram_message_id, db_path: Optional[str] = None) -> None:
    """Mark an FAA activity as posted to Telegram with its message ID."""
    _repo.mark_posted(mission, telegram_message_id, db_path)
