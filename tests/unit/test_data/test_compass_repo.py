"""Unit tests for COMPASS file persistence (``data.compass_repo``)."""

from __future__ import annotations

import pytest

from src.data.compass_repo import compass_files

pytestmark = pytest.mark.usefixtures("initialized_db")


def _file(uuid="u1", filename="deck 10 05 2026.pptx", uploaded="05/Oct/2026 14:26"):
    return {"file_uuid": uuid, "filename": filename, "uploaded_at": uploaded}


def test_new_file_needs_post(db_path):
    assert compass_files.save(_file(), db_path) == "inserted"

    rows = compass_files.needing_post(db_path)

    assert [r["file_uuid"] for r in rows] == ["u1"]
    assert rows[0]["filename"] == "deck 10 05 2026.pptx"
    assert rows[0]["uploaded_at"] == "05/Oct/2026 14:26"


def test_saving_same_file_twice_is_unchanged(db_path):
    compass_files.save(_file(), db_path)

    assert compass_files.save(_file(), db_path) == "unchanged"
    assert len(compass_files.needing_post(db_path)) == 1


def test_posted_file_is_not_reposted_when_renamed(db_path):
    compass_files.save(_file(), db_path)
    compass_files.mark_posted("u1", "42", db_path)

    assert compass_files.save(_file(filename="renamed.pptx"), db_path) == "updated"
    assert compass_files.needing_post(db_path) == []


def test_needing_post_is_in_insertion_order(db_path):
    for uuid in ("a", "b", "c"):
        compass_files.save(_file(uuid=uuid), db_path)

    assert [r["file_uuid"] for r in compass_files.needing_post(db_path)] == ["a", "b", "c"]


def test_bulk_mark_skips_already_posted(db_path):
    compass_files.save(_file(uuid="a"), db_path)
    compass_files.save(_file(uuid="b"), db_path)
    compass_files.mark_posted("a", "42", db_path)

    assert compass_files.mark_many_posted(["a", "b", "missing"], None, db_path) == 1
    assert compass_files.needing_post(db_path) == []


def test_record_without_uuid_is_skipped(db_path):
    assert compass_files.save({"filename": "x"}, db_path) == "skipped"
    assert compass_files.needing_post(db_path) == []


def test_count_compass_files(db_path):
    assert compass_files.count(db_path) == 0

    compass_files.save(_file("u1"), db_path)
    compass_files.save(_file("u2"), db_path)
    compass_files.mark_many_posted(["u1"], None, db_path)

    assert compass_files.count(db_path) == 2
