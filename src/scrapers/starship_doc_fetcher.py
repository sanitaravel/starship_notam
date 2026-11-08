"""HTTP-based SpaceX Starship documentary episode discovery.

SpaceX publishes its Starship documentary series as HLS videos at predictable
URLs (:data:`core.config.STARSHIP_DOC_URL`): episode *n* lives in
``StarshipDoc_Ep{n:03d}/``, with a master playlist ``StarshipDoc_EpNNN.m3u8``
(720p, 1080p and 4K renditions) next to ``StarshipDoc_EpNNN-4k.m3u8``. There is
no index of episodes, so new ones are found by probing the numbers after the
newest known episode: a released episode answers 200 with a playlist, an
unreleased one 404.

Probing looks :data:`core.config.STARSHIP_DOC_LOOKAHEAD` numbers ahead, so a
skipped or late episode number doesn't hide the ones after it. Unlike the
:class:`~src.scrapers.http_fetcher.HttpFetcher` sources this takes the
starting point as an argument and treats 404 as an answer, not a failure.
Parsing is delegated to :mod:`src.parsers.starship_doc_parser`.

The fetcher performs no persistence and never raises: on a failed request it
logs and returns ``None`` so callers can tell "fetch failed" apart from "no
new episodes".

Public API:
    starship_documentary_fetcher.fetch_after(latest: int) -> list[dict] | None
"""

from __future__ import annotations

import requests

from src.core import config
from src.core.logging import logger
from src.parsers.starship_doc_parser import parse_http_date, parse_media_playlist

# Statuses that mean "not published (yet)" rather than "request failed".
_NOT_RELEASED_STATUSES = frozenset({403, 404, 410})

# Returned by _probe for an episode that isn't online.
_NOT_RELEASED = object()


def episode_id(number: int) -> str:
    """``4`` -> ``"StarshipDoc_Ep004"``."""
    return f"StarshipDoc_Ep{number:03d}"


def episode_url(number: int, variant: str = "") -> str:
    """Playlist URL of episode *number*; ``variant`` ``""`` (master) or ``"-4k"``."""
    return config.STARSHIP_DOC_URL.format(id=episode_id(number), variant=variant)


class StarshipDocFetcher:
    """Probe episode playlists and describe the released episodes."""

    name = "Starship documentary"
    timeout: float = 30
    headers = {"User-Agent": "Mozilla/5.0 (compatible; starship_notam bot)"}

    def _probe(self, number: int):
        """Return episode *number*'s record, ``_NOT_RELEASED``, or None on failure."""
        url = episode_url(number, "-4k")
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
        except requests.RequestException:
            logger.exception("Failed to fetch %s from %s", self.name, url)
            return None
        if response.status_code in _NOT_RELEASED_STATUSES:
            logger.info("%s episode %d is not online (HTTP %d)",
                        self.name, number, response.status_code)
            return _NOT_RELEASED
        try:
            response.raise_for_status()
        except requests.RequestException:
            logger.exception("Failed to fetch %s from %s", self.name, url)
            return None

        playlist = parse_media_playlist(response.text)
        if playlist is None:
            return _NOT_RELEASED
        return {
            "episode_id": episode_id(number),
            "episode": number,
            "duration_seconds": playlist["duration_seconds"],
            "published_at": parse_http_date(response.headers.get("Last-Modified")),
            "master_url": episode_url(number),
            "playlist_url": url,
        }

    def fetch_after(self, latest: int, lookahead: int | None = None) -> list[dict] | None:
        """Return the released episodes numbered above *latest*, in order.

        Probing starts at ``latest + 1`` and stops after *lookahead*
        (default :data:`core.config.STARSHIP_DOC_LOOKAHEAD`) consecutive
        numbers that are not online. ``fetch_after(0)`` finds every episode.
        Returns None if any request fails.
        """
        lookahead = max(1, lookahead or config.STARSHIP_DOC_LOOKAHEAD)
        found: list[dict] = []
        misses = 0
        number = latest + 1
        while misses < lookahead:
            result = self._probe(number)
            if result is None:
                return None
            if result is _NOT_RELEASED:
                misses += 1
            else:
                found.append(result)
                misses = 0
            number += 1
        logger.info("Found %d new %s episode(s) after %d", len(found), self.name, latest)
        return found


starship_documentary_fetcher = StarshipDocFetcher()


if __name__ == "__main__":
    for e in starship_documentary_fetcher.fetch_after(0) or []:
        logger.info(f"Starship documentary episode: {e}")
