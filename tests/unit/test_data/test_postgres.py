"""Round-trip every repository against a real PostgreSQL database.

The rest of the data-layer suite runs on SQLite. These tests run only when
``TEST_DATABASE_URL`` points at a PostgreSQL database the tests may freely
drop tables in, e.g.::

    TEST_DATABASE_URL=postgresql://notam@localhost:5432/notam_test pytest
"""

import os

import pytest

from starship_notam.data import (
    get_beach_alerts_needing_post,
    compass_files,
    get_connection,
    faa_activities,
    faa_licenses,
    fcc_els_applications,
    get_notams_needing_images,
    get_road_alerts_needing_post,
    init_db,
    load_all_notams,
    mark_beach_posted,
    mark_image_generated,
    mark_road_posted,
    save_beach_alert,
    save_notam,
    save_road_alert,
)
from starship_notam.data.connection import is_postgres
from starship_notam.data.schema import _ADDED_COLUMNS

PG_URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not is_postgres(PG_URL), reason="TEST_DATABASE_URL is not a PostgreSQL URL"
)

_TABLES = (
    "notams",
    "faa_activities",
    "starbase_beach",
    "starbase_road",
    "fcc_els_applications",
    "faa_licenses",
    "compass_files",
)


@pytest.fixture
def pg():
    """Return the URL of an empty, freshly initialized PostgreSQL schema."""
    conn = get_connection(PG_URL)
    try:
        conn.execute(f"DROP TABLE IF EXISTS {', '.join(_TABLES)}")
        conn.commit()
    finally:
        conn.close()
    init_db(PG_URL)
    return PG_URL


def test_init_db_is_idempotent(pg):
    init_db(pg)


def test_init_db_adds_missing_columns(pg):
    conn = get_connection(pg)
    conn.execute("ALTER TABLE notams DROP COLUMN parsed_hash")
    conn.commit()
    conn.close()

    init_db(pg)

    conn = get_connection(pg)
    cur = conn.cursor()
    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
        ("notams",),
    )
    columns = {r["column_name"] for r in cur.fetchall()}
    conn.close()
    assert set(_ADDED_COLUMNS["notams"]) <= columns
    assert {"A", "Q_location"} <= columns


def test_notam_round_trip(pg, sample_parsed_notam):
    save_notam("A0001/26", sample_parsed_notam, pg)
    save_notam("A0001/26", sample_parsed_notam, pg)

    assert load_all_notams(pg) == [("A0001/26", sample_parsed_notam)]
    assert [n for n, _ in get_notams_needing_images(pg)] == ["A0001/26"]
    mark_image_generated("A0001/26", pg)
    assert get_notams_needing_images(pg) == []


def test_faa_activity_round_trip(pg):
    activity = {
        "mission": "Starship Flight Test",
        "primary_window": "08 JUL 25 1350-2359Z",
        "backup_window": "09 JUL 25 1350-2359Z",
    }
    faa_activities.save(activity, pg)

    assert faa_activities.needing_post(pg) == [activity]
    faa_activities.mark_posted(activity["mission"], 12345, pg)
    assert faa_activities.needing_post(pg) == []


def test_starbase_round_trip(pg):
    save_beach_alert(
        {
            "description": "Primary launch window closure.",
            "start_utc": "2026-07-08T18:00:00Z",
            "end_utc": "2026-07-09T05:00:00Z",
            "raw_date": "July 8",
            "periods": [{"label": "Primary", "text": "July 8"}],
        },
        pg,
    )
    save_road_alert(
        {
            "origin": "TX-4",
            "destination": "Boca Chica Beach",
            "description": "Road delay",
            "start_utc": "2026-07-08T17:00:00Z",
            "end_utc": "2026-07-08T23:59:00Z",
            "raw_date": "July 8",
        },
        pg,
    )

    (beach,) = get_beach_alerts_needing_post(pg)
    (road,) = get_road_alerts_needing_post(pg)
    mark_beach_posted(beach["alert_key"], pg)
    mark_road_posted(road["alert_key"], pg)
    assert get_beach_alerts_needing_post(pg) == []
    assert get_road_alerts_needing_post(pg) == []


def test_fcc_els_round_trip(pg):
    fcc_els_applications.save(
        {
            "file_number": "0123-EX-ST-2025",
            "application_seq": "12345",
            "applicant_name": "Space Exploration Technologies Corp.",
            "status": "Granted",
            "detail": {"Frequency": "2000 MHz"},
        },
        pg,
    )

    (app,) = fcc_els_applications.needing_post(pg)
    assert app["file_number"] == "0123-EX-ST-2025"
    fcc_els_applications.mark_posted("0123-EX-ST-2025", 12345, pg)
    assert fcc_els_applications.needing_post(pg) == []


def test_faa_license_round_trip(pg):
    faa_licenses.save(
        {"doc_unique_id": "DRSDOC1", "status": "Active", "details": {"a": "b"}}, pg
    )

    (lic,) = faa_licenses.needing_post(pg)
    assert lic["details"] == {"a": "b"}
    assert lic["is_new"]
    faa_licenses.mark_posted("DRSDOC1", 12345, pg)
    assert faa_licenses.needing_post(pg) == []


def test_compass_round_trip(pg):
    record = {"file_uuid": "u1", "filename": "deck.pptx", "uploaded_at": "05/Oct/2026"}
    assert compass_files.save(record, pg) == "inserted"
    assert compass_files.save(record, pg) == "unchanged"

    assert [r["file_uuid"] for r in compass_files.needing_post(pg)] == ["u1"]
    compass_files.mark_posted("u1", 12345, pg)
    assert compass_files.needing_post(pg) == []
