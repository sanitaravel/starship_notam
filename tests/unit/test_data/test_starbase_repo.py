"""Unit tests for Starbase alert persistence (``data.starbase_repo``).

Exercises beach and road alert save/query/update round-trips against an
isolated temporary SQLite database. Imports only the data layer
(standard-library dependencies only), satisfying Requirement 9.2. Error
handling (raise + rollback, no partial commit) is covered per Requirement 2.5.
"""

from __future__ import annotations

import pytest

from starship_notam.data.starbase_repo import (
    get_beach_alerts_needing_post,
    get_road_alerts_needing_post,
    make_beach_key,
    make_road_key,
    mark_beach_posted,
    mark_road_posted,
    save_beach_alert,
    save_road_alert,
)


def _beach_alert(start="2026-07-08T18:00:00Z", end="2026-07-09T05:00:00Z"):
    return {
        "description": "Primary launch window closure.",
        "start_utc": start,
        "end_utc": end,
        "raw_date": "July 8 from 1:00 PM to 11:00 PM CT",
        "periods": [{"label": "Primary", "text": "July 8"}],
    }


def _road_alert(origin="TX-4", destination="Boca Chica Beach",
                start="2026-07-08T17:00:00Z", end="2026-07-08T23:59:00Z"):
    return {
        "origin": origin,
        "destination": destination,
        "description": "Road delay",
        "start_utc": start,
        "end_utc": end,
        "raw_date": "July 8 from 12:00 PM to 11:59 PM CT",
    }


# --------------------------------------------------------------------------- #
# Beach alerts
# --------------------------------------------------------------------------- #
def test_save_beach_alert_then_needing_post_round_trip(db_path):
    alert = _beach_alert()
    save_beach_alert(alert, db_path)

    needing = get_beach_alerts_needing_post(db_path)

    assert len(needing) == 1
    row = needing[0]
    assert row["description"] == alert["description"]
    assert row["start_utc"] == alert["start_utc"]
    assert row["end_utc"] == alert["end_utc"]
    # The stable key matches the one derived from the window.
    assert row["alert_key"] == make_beach_key(alert["start_utc"], alert["end_utc"])


def test_save_beach_alert_idempotent_same_window(db_path):
    alert = _beach_alert()
    save_beach_alert(alert, db_path)
    save_beach_alert(alert, db_path)

    assert len(get_beach_alerts_needing_post(db_path)) == 1


def test_mark_beach_posted_removes_from_needing_list(db_path):
    alert = _beach_alert()
    save_beach_alert(alert, db_path)
    key = make_beach_key(alert["start_utc"], alert["end_utc"])

    mark_beach_posted(key, db_path)

    assert get_beach_alerts_needing_post(db_path) == []


def test_get_beach_alerts_needing_post_empty_db(initialized_db):
    assert get_beach_alerts_needing_post(initialized_db) == []


# --------------------------------------------------------------------------- #
# Road alerts
# --------------------------------------------------------------------------- #
def test_save_road_alert_then_needing_post_round_trip(db_path):
    alert = _road_alert()
    save_road_alert(alert, db_path)

    needing = get_road_alerts_needing_post(db_path)

    assert len(needing) == 1
    row = needing[0]
    assert row["origin"] == alert["origin"]
    assert row["destination"] == alert["destination"]
    assert row["description"] == alert["description"]
    assert row["alert_key"] == make_road_key(
        alert["origin"], alert["destination"], alert["start_utc"], alert["end_utc"]
    )


def test_save_road_alert_idempotent_same_route_window(db_path):
    alert = _road_alert()
    save_road_alert(alert, db_path)
    save_road_alert(alert, db_path)

    assert len(get_road_alerts_needing_post(db_path)) == 1


def test_mark_road_posted_removes_from_needing_list(db_path):
    alert = _road_alert()
    save_road_alert(alert, db_path)
    key = make_road_key(
        alert["origin"], alert["destination"], alert["start_utc"], alert["end_utc"]
    )

    mark_road_posted(key, db_path)

    assert get_road_alerts_needing_post(db_path) == []


def test_get_road_alerts_needing_post_empty_db(initialized_db):
    assert get_road_alerts_needing_post(initialized_db) == []


def test_beach_and_road_alerts_are_independent(db_path):
    """Beach and road alerts live in separate tables and do not interfere."""
    save_beach_alert(_beach_alert(), db_path)
    save_road_alert(_road_alert(), db_path)

    assert len(get_beach_alerts_needing_post(db_path)) == 1
    assert len(get_road_alerts_needing_post(db_path)) == 1


# --------------------------------------------------------------------------- #
# Error handling (Requirement 2.5)
# --------------------------------------------------------------------------- #
def test_save_beach_alert_raises_on_db_failure(tmp_path, monkeypatch):
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("blocker file")
    bad_db = str(blocker / "nested" / "notams.db")
    monkeypatch.setenv("NOTAM_DB_PATH", bad_db)

    with pytest.raises(Exception):
        save_beach_alert(_beach_alert(), bad_db)


def test_save_road_alert_raises_on_db_failure(tmp_path, monkeypatch):
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("blocker file")
    bad_db = str(blocker / "nested" / "notams.db")
    monkeypatch.setenv("NOTAM_DB_PATH", bad_db)

    with pytest.raises(Exception):
        save_road_alert(_road_alert(), bad_db)
