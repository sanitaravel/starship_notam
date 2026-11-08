"""Unit tests for Starship documentary episode discovery (``scrapers.starship_doc_fetcher``)."""

from __future__ import annotations

import pytest
import requests

from src.core import config
from src.scrapers import starship_documentary_fetcher as package_export
import src.scrapers.starship_doc_fetcher as fetcher_module
from src.scrapers.starship_doc_fetcher import (
    episode_id,
    episode_url,
    starship_documentary_fetcher,
)

PLAYLIST = "#EXTM3U\n#EXTINF:60.4,\na.ts\n#EXTINF:30.0,\nb.ts\n#EXT-X-ENDLIST\n"


class FakeResponse:
    def __init__(self, status_code=200, text=PLAYLIST, headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers if headers is not None else {
            "Last-Modified": "Fri, 06 Nov 2026 13:44:03 GMT"
        }

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


@pytest.fixture
def online(monkeypatch):
    """Serve episode numbers in ``online.numbers``; everything else is a 404.

    ``online.overrides`` maps a number to a response or an exception to raise.
    """
    calls = []

    def fake_get(url, **kwargs):
        number = int(url.rsplit("Ep", 1)[1][:3])
        calls.append(number)
        override = fake_get.overrides.get(number)
        if isinstance(override, Exception):
            raise override
        if override is not None:
            return override
        return FakeResponse() if number in fake_get.numbers else FakeResponse(404, "<Error/>")

    fake_get.numbers = set()
    fake_get.overrides = {}
    fake_get.calls = calls
    monkeypatch.setattr(fetcher_module.requests, "get", fake_get)
    return fake_get


def test_urls():
    assert episode_id(4) == "StarshipDoc_Ep004"
    assert episode_url(4) == (
        "https://content.spacex.com/cms-assets/content-hub/documentary/"
        "StarshipDoc_Ep004/StarshipDoc_Ep004.m3u8"
    )
    assert episode_url(4, "-4k").endswith("/StarshipDoc_Ep004/StarshipDoc_Ep004-4k.m3u8")


def test_exported_from_package():
    assert package_export is starship_documentary_fetcher


def test_fetch_after_zero_finds_every_episode(online):
    online.numbers = {1, 2, 3, 4}

    episodes = starship_documentary_fetcher.fetch_after(0)

    assert [e["episode"] for e in episodes] == [1, 2, 3, 4]
    assert episodes[3] == {
        "episode_id": "StarshipDoc_Ep004",
        "episode": 4,
        "duration_seconds": 90,
        "published_at": "2026-11-06T13:44:03Z",
        "master_url": episode_url(4),
        "playlist_url": episode_url(4, "-4k"),
    }
    # Probing stops after the default lookahead of 2 misses: Ep005, Ep006.
    assert online.calls == [1, 2, 3, 4, 5, 6]


def test_nothing_new_probes_only_the_lookahead(online):
    online.numbers = {1, 2}

    assert starship_documentary_fetcher.fetch_after(2) == []
    assert online.calls == [3, 4]


def test_gap_within_lookahead_does_not_hide_later_episode(online):
    online.numbers = {1, 3}

    episodes = starship_documentary_fetcher.fetch_after(0)

    assert [e["episode"] for e in episodes] == [1, 3]
    assert online.calls == [1, 2, 3, 4, 5]


def test_gap_beyond_lookahead_stops_probing(online, monkeypatch):
    online.numbers = {1, 4}
    monkeypatch.setattr(config, "STARSHIP_DOC_LOOKAHEAD", 2)

    assert [e["episode"] for e in starship_documentary_fetcher.fetch_after(0)] == [1]


def test_lookahead_can_be_widened(online, monkeypatch):
    online.numbers = {1, 4}
    monkeypatch.setattr(config, "STARSHIP_DOC_LOOKAHEAD", 3)

    assert [e["episode"] for e in starship_documentary_fetcher.fetch_after(0)] == [1, 4]


@pytest.mark.parametrize("status", [403, 404, 410])
def test_not_released_statuses_are_not_failures(online, status):
    online.overrides = {1: FakeResponse(status, "<Error/>"), 2: FakeResponse(status, "")}

    assert starship_documentary_fetcher.fetch_after(0) == []


def test_server_error_is_a_failed_fetch(online):
    online.numbers = {1}
    online.overrides = {2: FakeResponse(500, "oops")}

    assert starship_documentary_fetcher.fetch_after(0) is None


def test_network_error_is_a_failed_fetch(online):
    online.overrides = {1: requests.ConnectionError("down")}

    assert starship_documentary_fetcher.fetch_after(0) is None


def test_200_that_is_not_a_playlist_counts_as_not_released(online):
    spa = FakeResponse(200, "<html>SPA</html>")
    online.overrides = {1: spa, 2: spa}

    assert starship_documentary_fetcher.fetch_after(0) == []


def test_missing_last_modified_gives_empty_published_at(online):
    online.overrides = {1: FakeResponse(headers={})}

    (episode,) = starship_documentary_fetcher.fetch_after(0)

    assert episode["published_at"] == ""
