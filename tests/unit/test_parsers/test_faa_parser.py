"""Unit tests for :mod:`starship_notam.parsers.faa_parser`.

Covers ``parse_faa_advisory_html`` with sample HTML plus a determinism
check (Requirement 3.6).

Imports only the parsers layer (Requirements 9.1, 9.4).
"""

from __future__ import annotations

from starship_notam.parsers import parse_faa_advisory_html


def test_parses_planned_launch_block(sample_faa_advisory_html):
    result = parse_faa_advisory_html(sample_faa_advisory_html)

    assert isinstance(result, list)
    assert len(result) == 1

    launch = result[0]
    assert launch["mission"] == "STARSHIP FLIGHT TEST, BOCA CHICA, TX"
    assert launch["primary_window"] == "08 JUL 25 1350-2359Z"
    assert launch["backup_window"] == "09 JUL 25 1350-2359Z"


def test_launch_dict_has_required_keys(sample_faa_advisory_html):
    result = parse_faa_advisory_html(sample_faa_advisory_html)

    for launch in result:
        assert set(launch.keys()) == {
            "mission",
            "primary_window",
            "backup_window",
        }


def test_no_planned_launch_returns_empty_list():
    html = "<html><body><pre>NOTHING RELEVANT HERE</pre></body></html>"

    assert parse_faa_advisory_html(html) == []


def test_launch_without_backup_window():
    html = (
        "<html><body><pre>"
        "PLANNED LAUNCH/REENTRY:\n"
        "FALCON MISSION, CAPE CANAVERAL, FL\n"
        "PRIMARY: 10 JUL 25 0000-0600Z\n"
        "FLIGHT CHECK(S): NONE\n"
        "</pre></body></html>"
    )
    result = parse_faa_advisory_html(html)

    assert len(result) == 1
    assert result[0]["mission"] == "FALCON MISSION, CAPE CANAVERAL, FL"
    assert result[0]["primary_window"] == "10 JUL 25 0000-0600Z"
    assert result[0]["backup_window"] is None


def test_multiple_launches():
    html = (
        "<html><body><pre>"
        "PLANNED LAUNCH/REENTRY:\n"
        "MISSION ONE, SITE A, TX\n"
        "PRIMARY: 08 JUL 25 1000-1200Z\n"
        "MISSION TWO, SITE B, FL\n"
        "PRIMARY: 09 JUL 25 1000-1200Z\n"
        "BACKUP: 10 JUL 25 1000-1200Z\n"
        "FLIGHT CHECK(S): NONE\n"
        "</pre></body></html>"
    )
    result = parse_faa_advisory_html(html)

    assert [launch["mission"] for launch in result] == [
        "MISSION ONE, SITE A, TX",
        "MISSION TWO, SITE B, FL",
    ]
    assert result[0]["backup_window"] is None
    assert result[1]["backup_window"] == "10 JUL 25 1000-1200Z"


# ---------------------------------------------------------------------------
# Determinism (Requirement 3.6)
# ---------------------------------------------------------------------------
def test_parse_faa_advisory_html_is_deterministic(sample_faa_advisory_html):
    assert parse_faa_advisory_html(sample_faa_advisory_html) == (
        parse_faa_advisory_html(sample_faa_advisory_html)
    )
