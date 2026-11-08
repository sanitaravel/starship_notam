"""Unit tests for Starship documentary playlist parsing (``parsers.starship_doc_parser``)."""

from __future__ import annotations

from src.parsers.starship_doc_parser import parse_http_date, parse_media_playlist

# Head of a real media playlist (Ep003, 4K), shortened to a few segments.
PLAYLIST = """#EXTM3U
#EXT-X-VERSION:6
#EXT-X-TARGETDURATION:4
#EXT-X-MEDIA-SEQUENCE:0
#EXT-X-PLAYLIST-TYPE:VOD
#EXT-X-INDEPENDENT-SEGMENTS
#EXTINF:2.002000,
StarshipDoc_Ep003-4k0.ts
#EXTINF:2.002000,
StarshipDoc_Ep003-4k1.ts
#EXTINF:3.795456,
StarshipDoc_Ep003-4k3.ts
#EXT-X-ENDLIST
"""

# The master playlist of Ep004 lists renditions, not segments.
MASTER = """#EXTM3U
#EXT-X-VERSION:6
#EXT-X-STREAM-INF:BANDWIDTH=5922400,RESOLUTION=1280x720,CODECS="avc1.64001f,mp4a.40.2"
StarshipDoc_Ep004-720p.m3u8
"""


def test_media_playlist_sums_segment_durations():
    assert parse_media_playlist(PLAYLIST) == {"duration_seconds": 8, "segments": 3}


def test_master_playlist_has_no_segments():
    assert parse_media_playlist(MASTER) == {"duration_seconds": 0, "segments": 0}


def test_unreadable_segment_duration_is_skipped():
    text = "#EXTM3U\n#EXTINF:abc,\na.ts\n#EXTINF:10.4,\nb.ts\n"

    assert parse_media_playlist(text) == {"duration_seconds": 10, "segments": 1}


def test_non_playlist_is_none():
    assert parse_media_playlist("<html>SPA</html>") is None
    assert parse_media_playlist("") is None
    assert parse_media_playlist(None) is None


def test_http_date_is_converted_to_iso_utc():
    assert parse_http_date("Fri, 06 Nov 2026 13:44:03 GMT") == "2026-11-06T13:44:03Z"


def test_http_date_unreadable_is_empty():
    assert parse_http_date(None) == ""
    assert parse_http_date("") == ""
    assert parse_http_date("yesterday-ish") == ""
