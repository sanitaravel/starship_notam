"""Unit tests for USCG BNM persistence (``data.uscg_bnm_repo``)."""

from __future__ import annotations

import pytest

from src.data.uscg_bnm_repo import uscg_bnm_notices

pytestmark = pytest.mark.usefixtures("initialized_db")


def _notice(kind="SAFETY", bnm_id="CGD-H BNM 0108-26", **extra):
    return {
        "notice_key": f"{kind} {bnm_id}",
        "bnm_id": bnm_id,
        "kind": kind,
        "region": "TX - GULF OF AMERICA",
        "title": f"{kind}/TX - GULF OF AMERICA/SPACE OPERATIONS/{bnm_id}",
        "flight": "14",
        "mission": "STARSHIP FLIGHT 14",
        "starship": True,
        "areas": [{"label": "HAZARD AREA", "coords": [[25.9, -97.2], [26.0, -97.2]]}],
        "windows": [["2026-09-28T12:15:00Z", "2026-09-28T14:14:00Z"]],
        "cancel_at": "2026-10-04T15:14:00Z",
        "cancels": "",
        "outcome": "",
        "published_at": "2026-09-25T18:24:01Z",
        "link": "https://example.org/b",
        **extra,
    }


def test_new_notice_needs_post_with_areas_and_windows_decoded(db_path):
    assert uscg_bnm_notices.save(_notice(), db_path) == "inserted"

    [row] = uscg_bnm_notices.needing_post(db_path)

    assert row["notice_key"] == "SAFETY CGD-H BNM 0108-26"
    assert row["flight"] == "14"
    assert row["areas"] == [
        {"label": "HAZARD AREA", "coords": [[25.9, -97.2], [26.0, -97.2]]}
    ]
    assert row["windows"] == [["2026-09-28T12:15:00Z", "2026-09-28T14:14:00Z"]]
    assert "areas_json" not in row


def test_cancellation_is_a_separate_row(db_path):
    uscg_bnm_notices.save(_notice(), db_path)
    uscg_bnm_notices.save(
        _notice("CANCELLATION", areas=[], windows=[], cancels="CGD-H BNM 0108-26"),
        db_path,
    )

    rows = uscg_bnm_notices.needing_post(db_path)

    assert [r["notice_key"] for r in rows] == [
        "SAFETY CGD-H BNM 0108-26",
        "CANCELLATION CGD-H BNM 0108-26",
    ]
    assert rows[1]["areas"] == []


def test_posted_notice_is_not_reposted(db_path):
    uscg_bnm_notices.save(_notice(), db_path)
    uscg_bnm_notices.mark_posted("SAFETY CGD-H BNM 0108-26", "7", db_path)

    assert uscg_bnm_notices.save(_notice(), db_path) == "unchanged"
    assert uscg_bnm_notices.save(_notice(outcome="x"), db_path) == "updated"
    assert uscg_bnm_notices.needing_post(db_path) == []


def test_notice_without_key_is_skipped(db_path):
    assert uscg_bnm_notices.save({"bnm_id": "x"}, db_path) == "skipped"
