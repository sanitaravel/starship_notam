"""SpaceX Starship documentary playlist parsing.

Each episode of SpaceX's Starship documentary series is published as an HLS
video under ``content.spacex.com`` (see :data:`core.config.STARSHIP_DOC_URL`).
The fetcher downloads one rendition's media playlist, a plain-text VOD
playlist listing the video's segments::

    #EXTM3U
    #EXT-X-VERSION:6
    #EXT-X-TARGETDURATION:4
    #EXT-X-MEDIA-SEQUENCE:0
    #EXT-X-PLAYLIST-TYPE:VOD
    #EXT-X-INDEPENDENT-SEGMENTS
    #EXTINF:2.002000,
    StarshipDoc_Ep003-4k0.ts
    #EXTINF:3.795456,
    StarshipDoc_Ep003-4k1.ts
    ...

and its ``Last-Modified`` header (``Fri, 06 Nov 2026 13:44:03 GMT``), which
dates the upload.

It performs no network, database, or filesystem operations.

Public API:
    parse_media_playlist(text: str) -> dict | None
    parse_http_date(value: str | None) -> str
"""

from __future__ import annotations

from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Optional

from src.core.logging import logger


def parse_media_playlist(text: str) -> Optional[dict]:
    """Summarize an HLS media playlist.

    Returns ``{"duration_seconds": int, "segments": int}``, the total of the
    ``#EXTINF`` durations rounded to whole seconds and the number of segments,
    or None when *text* is not an HLS playlist (no ``#EXTM3U`` header).
    """
    lines = [line.strip() for line in (text or "").splitlines()]
    if not lines or lines[0] != "#EXTM3U":
        logger.warning("Starship documentary response is not an HLS playlist")
        return None

    total = 0.0
    segments = 0
    for line in lines:
        if not line.startswith("#EXTINF:"):
            continue
        value = line[len("#EXTINF:"):].split(",", 1)[0]
        try:
            total += float(value)
        except ValueError:
            logger.warning("Skipping unreadable segment duration %r", value)
            continue
        segments += 1
    return {"duration_seconds": round(total), "segments": segments}


def parse_http_date(value: Optional[str]) -> str:
    """``"Fri, 06 Nov 2026 13:44:03 GMT"`` -> ``"2026-11-06T13:44:03Z"``; ``""`` if unreadable."""
    if not value:
        return ""
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
