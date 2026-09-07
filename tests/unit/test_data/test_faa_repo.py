"""Unit tests for FAA activity persistence (``data.faa_repo``).

Exercises save/query/update round-trips against an isolated temporary SQLite
database. Imports only the data layer (standard-library dependencies only),
satisfying Requirement 9.2. Error handling is covered per Requirement 2.5.
"""

from __future__ import annotations

import pytest

from starship_notam.data.connection import get_connection
from starship_notam.data.faa_repo import (
    get_faa_activities_needing_post,
    mark_faa_activity_posted,
    save_faa_activity,
)


def _activity(mission="Starship Flight Test", primary="08 JUL 25 1350-2359Z",
              backup="09 JUL 25 1350-2359Z"):
    return {
        "mission": mission,
        "primary_window": primary,
        "backup_window": backup,
    }


def test_save_faa_activity_then_needing_post_round_trip(db_path):
    """A newly saved activity is returned by get_faa_activities_needing_post."""
    activity = _activity()
    save_faa_activity(activity, db_path)

    needing = get_faa_activities_needing_post(db_path)

    assert len(needing) == 1
    row = needing[0]
    assert row["mission"] == activity["mission"]
    assert row["primary_window"] == activity["primary_window"]
    assert row["backup_window"] == activity["backup_window"]


def test_save_faa_activity_is_idempotent(db_path):
    """Saving the same activity twice does not create a duplicate row."""
    activity = _activity()
    save_faa_activity(activity, db_path)
    save_faa_activity(activity, db_path)

    assert len(get_faa_activities_needing_post(db_path)) == 1


def test_save_faa_activity_updates_windows_on_change(db_path):
    """Changing the windows updates the stored record in place (no duplicate)."""
    save_faa_activity(_activity(), db_path)
    save_faa_activity(_activity(primary="10 JUL 25 1350-2359Z"), db_path)

    needing = get_faa_activities_needing_post(db_path)
    assert len(needing) == 1
    assert needing[0]["primary_window"] == "10 JUL 25 1350-2359Z"


def test_mark_faa_activity_posted_removes_from_needing_list(db_path):
    """After marking an activity posted, it drops out of the needing-post list."""
    activity = _activity()
    save_faa_activity(activity, db_path)
    assert get_faa_activities_needing_post(db_path)  # sanity: present

    mark_faa_activity_posted(activity["mission"], "msg-123", db_path)

    assert get_faa_activities_needing_post(db_path) == []


def test_mark_faa_activity_posted_persists_message_id(db_path):
    """Marking posted records the telegram_message_id and posted flag."""
    activity = _activity()
    save_faa_activity(activity, db_path)

    mark_faa_activity_posted(activity["mission"], "msg-999", db_path)

    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT telegram_posted, telegram_message_id FROM faa_activities "
            "WHERE mission = ?",
            (activity["mission"],),
        )
        row = cur.fetchone()
    finally:
        conn.close()

    assert row["telegram_posted"] == 1
    assert row["telegram_message_id"] == "msg-999"


def test_get_faa_activities_needing_post_empty_db(initialized_db):
    """An initialized-but-empty database yields no activities needing posting."""
    assert get_faa_activities_needing_post(initialized_db) == []


def test_save_faa_activity_raises_on_db_failure(tmp_path, monkeypatch):
    """A write failure against an unusable DB path propagates to the caller.

    Pointing at a path whose parent is a file makes SQLite unable to open the
    database, so init_db (called first) raises rather than silently succeeding
    (Requirement 2.5).
    """
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("blocker file")
    bad_db = str(blocker / "nested" / "notams.db")
    monkeypatch.setenv("NOTAM_DB_PATH", bad_db)

    with pytest.raises(Exception):
        save_faa_activity(_activity(), bad_db)
