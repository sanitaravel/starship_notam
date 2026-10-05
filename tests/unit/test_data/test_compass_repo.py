"""Unit tests for COMPASS file persistence (``data.compass_repo``)."""

from __future__ import annotations

import pytest

from starship_notam.data.compass_repo import (
    get_compass_files_needing_post,
    mark_compass_file_posted,
    mark_compass_files_posted,
    save_compass_file,
)

pytestmark = pytest.mark.usefixtures("initialized_db")


def _file(uuid="u1", filename="deck 10 05 2026.pptx", uploaded="05/Oct/2026 14:26"):
    return {"file_uuid": uuid, "filename": filename, "uploaded_at": uploaded}


def test_new_file_needs_post(db_path):
    assert save_compass_file(_file(), db_path) == "inserted"

    rows = get_compass_files_needing_post(db_path)

    assert [r["file_uuid"] for r in rows] == ["u1"]
    assert rows[0]["filename"] == "deck 10 05 2026.pptx"
    assert rows[0]["uploaded_at"] == "05/Oct/2026 14:26"


def test_saving_same_file_twice_is_unchanged(db_path):
    save_compass_file(_file(), db_path)

    assert save_compass_file(_file(), db_path) == "unchanged"
    assert len(get_compass_files_needing_post(db_path)) == 1


def test_posted_file_is_not_reposted_when_renamed(db_path):
    save_compass_file(_file(), db_path)
    mark_compass_file_posted("u1", "42", db_path)

    assert save_compass_file(_file(filename="renamed.pptx"), db_path) == "updated"
    assert get_compass_files_needing_post(db_path) == []


def test_needing_post_is_in_insertion_order(db_path):
    for uuid in ("a", "b", "c"):
        save_compass_file(_file(uuid=uuid), db_path)

    assert [r["file_uuid"] for r in get_compass_files_needing_post(db_path)] == ["a", "b", "c"]


def test_bulk_mark_skips_already_posted(db_path):
    save_compass_file(_file(uuid="a"), db_path)
    save_compass_file(_file(uuid="b"), db_path)
    mark_compass_file_posted("a", "42", db_path)

    assert mark_compass_files_posted(["a", "b", "missing"], None, db_path) == 1
    assert get_compass_files_needing_post(db_path) == []


def test_record_without_uuid_is_skipped(db_path):
    assert save_compass_file({"filename": "x"}, db_path) == "skipped"
    assert get_compass_files_needing_post(db_path) == []
