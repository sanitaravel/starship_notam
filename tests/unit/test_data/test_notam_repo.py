"""Unit tests for the NOTAM persistence layer (``data.notam_repo``).

These tests exercise the real SQLite connection factory and schema-creation
logic against an isolated, temporary database (see the ``db_path`` /
``initialized_db`` fixtures in ``tests/conftest.py``). No Selenium, Telegram, or
Cartopy imports are required — the data layer depends only on the standard
library, satisfying Requirement 9.2.

Covers save/load round-trips and error handling per Requirements 2.5 and 9.2.
"""

from __future__ import annotations

import os

import pytest

from starship_notam.data.notam_repo import (
    get_notams_needing_images,
    load_all_notams,
    mark_image_generated,
    save_notam,
)


def test_save_notam_then_load_all_round_trip(db_path, sample_parsed_notam):
    """A saved NOTAM is returned verbatim (structured fields) by load_all_notams."""
    save_notam("NOTAM-1", sample_parsed_notam, db_path)

    loaded = load_all_notams(db_path)

    assert len(loaded) == 1
    name, parsed = loaded[0]
    assert name == "NOTAM-1"
    # Scalar ICAO fields round-trip.
    for field in ("A", "B", "C", "E", "F", "G"):
        assert parsed[field] == sample_parsed_notam[field]
    # Q sub-dict round-trips.
    assert parsed["Q"] == sample_parsed_notam["Q"]


def test_load_all_notams_orders_by_name(db_path, sample_parsed_notam):
    """load_all_notams returns records ordered by name."""
    save_notam("BBB", sample_parsed_notam, db_path)
    save_notam("AAA", sample_parsed_notam, db_path)
    save_notam("CCC", sample_parsed_notam, db_path)

    names = [name for name, _ in load_all_notams(db_path)]

    assert names == ["AAA", "BBB", "CCC"]


def test_load_all_notams_missing_db_returns_empty(db_path):
    """When the database file does not exist, load_all_notams returns []."""
    assert not os.path.exists(db_path)
    assert load_all_notams(db_path) == []


def test_new_notam_needs_image(db_path, sample_parsed_notam):
    """A freshly saved NOTAM has image_generated == 0 and needs an image."""
    save_notam("NOTAM-IMG", sample_parsed_notam, db_path)

    needing = get_notams_needing_images(db_path)

    assert [name for name, _ in needing] == ["NOTAM-IMG"]


def test_mark_image_generated_removes_from_needing_list(db_path, sample_parsed_notam):
    """After marking the image generated, the NOTAM no longer needs an image."""
    save_notam("NOTAM-IMG", sample_parsed_notam, db_path)
    assert get_notams_needing_images(db_path)  # sanity: present before

    mark_image_generated("NOTAM-IMG", db_path)

    assert get_notams_needing_images(db_path) == []
    # The record still exists overall.
    assert [name for name, _ in load_all_notams(db_path)] == ["NOTAM-IMG"]


def test_get_notams_needing_images_missing_db_returns_empty(db_path):
    """get_notams_needing_images creates the schema, so an empty DB yields []."""
    result = get_notams_needing_images(db_path)
    assert result == []


def test_save_notam_update_resets_image_generated(db_path, sample_parsed_notam):
    """Re-saving a NOTAM with changed content resets image_generated to 0."""
    save_notam("NOTAM-CHG", sample_parsed_notam, db_path)
    mark_image_generated("NOTAM-CHG", db_path)
    assert get_notams_needing_images(db_path) == []

    changed = dict(sample_parsed_notam)
    changed["E"] = "UPDATED LAUNCH OPERATIONS DESCRIPTION."
    save_notam("NOTAM-CHG", changed, db_path)

    needing = get_notams_needing_images(db_path)
    assert [name for name, _ in needing] == ["NOTAM-CHG"]


def test_save_notam_is_idempotent_for_identical_payload(db_path, sample_parsed_notam):
    """Saving the same NOTAM twice does not create a duplicate row."""
    save_notam("NOTAM-DUP", sample_parsed_notam, db_path)
    save_notam("NOTAM-DUP", sample_parsed_notam, db_path)

    assert len([n for n, _ in load_all_notams(db_path)]) == 1


def test_save_notam_raises_on_db_failure_no_partial_commit(tmp_path, monkeypatch):
    """A write failure raises to the caller without leaving a partial commit.

    We point NOTAM_DB_PATH at a path whose parent is a *file* (not a
    directory), so SQLite cannot open/create the database. The failure must
    propagate rather than be silently swallowed (Requirement 2.5).
    """
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("i am a file, not a directory")
    bad_db = str(blocker / "nested" / "notams.db")
    monkeypatch.setenv("NOTAM_DB_PATH", bad_db)

    with pytest.raises(Exception):
        save_notam("NOTAM-FAIL", {"A": "KZHU"}, bad_db)

    # No database file/artifact was created at the bad location.
    assert not os.path.exists(bad_db)
