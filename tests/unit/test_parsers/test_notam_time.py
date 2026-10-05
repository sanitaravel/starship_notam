"""Tests for the shared NOTAM B)/C) time parser."""

from datetime import datetime, timedelta, timezone

import pytest

from starship_notam.parsers.notam_parser import _try_parse_dt
from starship_notam.parsers.notam_time import parse_notam_time

JUL_8 = datetime(2026, 7, 8, 13, 50)


@pytest.mark.parametrize(
    "raw",
    [
        "2607081350",  # raw FAA field
        "2607081350EST",
        " 2607081350 EST ",
        "202607081350",
        "2026-07-08T13:50:00Z",  # stored form
        "2026-07-08T13:50:00",
        "2026-07-08 13:50",
        "2026-07-08T15:50:00+02:00",
        "20260708T1350",
        JUL_8,
        JUL_8.replace(tzinfo=timezone.utc),
        datetime(2026, 7, 8, 8, 50, tzinfo=timezone(timedelta(hours=-5))),
    ],
)
def test_parses_to_naive_utc(raw):
    assert parse_notam_time(raw) == JUL_8


@pytest.mark.parametrize("raw", [None, "", "PERM", "abc", "2613991350"])
def test_unparseable_gives_none(raw):
    assert parse_notam_time(raw) is None


def test_try_parse_dt_stores_iso_or_raw_text():
    assert _try_parse_dt("2607081350EST") == "2026-07-08T13:50:00Z"
    assert _try_parse_dt(" PERM ") == "PERM"
    assert _try_parse_dt(None) is None
