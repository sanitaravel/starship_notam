"""Unit tests for Starship documentary persistence (``data.starship_doc_repo``)."""

from __future__ import annotations

import pytest

from src.data.starship_doc_repo import starship_documentaries

pytestmark = pytest.mark.usefixtures("initialized_db")


def _episode(number=4, **extra):
    return {
        "episode_id": f"StarshipDoc_Ep{number:03d}",
        "episode": number,
        "duration_seconds": 1270,
        "published_at": "2026-11-06T13:44:03Z",
        "master_url": f"https://example.org/Ep{number:03d}.m3u8",
        "playlist_url": f"https://example.org/Ep{number:03d}-4k.m3u8",
        **extra,
    }


def test_save_then_needing_post(initialized_db):
    assert starship_documentaries.save(_episode(), initialized_db) == "inserted"

    (row,) = starship_documentaries.needing_post(initialized_db)
    assert row["episode_id"] == "StarshipDoc_Ep004"
    assert row["episode"] == 4
    assert row["duration_seconds"] == 1270
    assert row["published_at"] == "2026-11-06T13:44:03Z"
    assert row["playlist_url"].endswith("-4k.m3u8")
    assert row["telegram_posted"] == 0


def test_unchanged_save_is_a_noop(initialized_db):
    starship_documentaries.save(_episode(), initialized_db)

    assert starship_documentaries.save(_episode(), initialized_db) == "unchanged"
    assert len(starship_documentaries.needing_post(initialized_db)) == 1


def test_changed_episode_is_not_reposted(initialized_db):
    starship_documentaries.save(_episode(), initialized_db)
    starship_documentaries.mark_posted("StarshipDoc_Ep004", "42", initialized_db)

    assert starship_documentaries.save(_episode(duration_seconds=1300), initialized_db) == "updated"
    assert starship_documentaries.needing_post(initialized_db) == []


def test_needing_post_is_ordered_by_episode(initialized_db):
    for number in (3, 1, 2):
        starship_documentaries.save(_episode(number), initialized_db)

    rows = starship_documentaries.needing_post(initialized_db)

    assert [r["episode"] for r in rows] == [1, 2, 3]


def test_latest_episode(initialized_db):
    assert starship_documentaries.latest_episode(initialized_db) == 0

    starship_documentaries.save(_episode(2), initialized_db)
    starship_documentaries.save(_episode(5), initialized_db)
    starship_documentaries.save(_episode(3), initialized_db)
    starship_documentaries.mark_many_posted(["StarshipDoc_Ep005"], None, initialized_db)

    # Posted or not, the highest stored number is where probing resumes.
    assert starship_documentaries.latest_episode(initialized_db) == 5


@pytest.mark.parametrize(
    "record",
    [{}, {"episode": 4}, {"episode_id": "StarshipDoc_Ep004"},
     {"episode_id": "StarshipDoc_Ep004", "episode": "4"}],
)
def test_incomplete_record_is_skipped(initialized_db, record):
    assert starship_documentaries.save(record, initialized_db) == "skipped"
    assert starship_documentaries.needing_post(initialized_db) == []
