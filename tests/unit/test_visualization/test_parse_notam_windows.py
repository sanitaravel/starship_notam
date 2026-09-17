"""Tests for :func:`parse_notam_windows` schedule parsing.

Focus: the multi-day / month-token FAA schedule layout that previously
collapsed to a single ``Ежедневно`` line, dropping all the specific dates.
The regression cases lock in the behavior for the simpler shapes so the
richer parser cannot silently change them.
"""
from datetime import datetime, timezone

from starship_notam.visualization.image_composer import parse_notam_windows

# NOTAM start (field B) 2609282107 -> 2026-09-28 21:07 UTC.
BASE = datetime(2026, 9, 28, 21, 7, tzinfo=timezone.utc)


def test_multi_month_daily_range_expands_to_every_day():
    """The reported failing D-field must list each day, not one DLY line.

    ``SEP 26-29 29-30`` then ``30-OCT 01 01-02 ... 04-05`` with a shared
    2107-0108 window covers Sep 26 through Oct 05 daily.
    """
    d = (
        "SEP 26-29 29-30 BTN 2107-0108\n"
        "30-OCT 01 01-02 02-03 03-04 04-05 DLY BTN 2107-0108"
    )
    assert parse_notam_windows(d, BASE) == [
        "Сентябрь 26, 21:07 - 01:08",
        "Сентябрь 27, 21:07 - 01:08",
        "Сентябрь 28, 21:07 - 01:08",
        "Сентябрь 29, 21:07 - 01:08",
        "Сентябрь 30, 21:07 - 01:08",
        "Октябрь 01, 21:07 - 01:08",
        "Октябрь 02, 21:07 - 01:08",
        "Октябрь 03, 21:07 - 01:08",
        "Октябрь 04, 21:07 - 01:08",
        "Октябрь 05, 21:07 - 01:08",
    ]


def test_month_token_sets_month_for_following_days():
    d = "SEP 26 27 OCT 01 02 BTN 2107-0108"
    assert parse_notam_windows(d, BASE) == [
        "Сентябрь 26, 21:07 - 01:08",
        "Сентябрь 27, 21:07 - 01:08",
        "Октябрь 01, 21:07 - 01:08",
        "Октябрь 02, 21:07 - 01:08",
    ]


def test_multiple_ranges_share_trailing_window():
    d = "SEP 26-27 28-29 BTN 2107-0108"
    assert parse_notam_windows(d, BASE) == [
        "Сентябрь 26, 21:07 - 01:08",
        "Сентябрь 27, 21:07 - 01:08",
        "Сентябрь 28, 21:07 - 01:08",
        "Сентябрь 29, 21:07 - 01:08",
    ]


# --- regression: simpler shapes must be unchanged by the richer parser ---

def test_regression_daily_window():
    assert parse_notam_windows("DLY 0800-2059", BASE) == ["Ежедневно 08:00 - 20:59"]


def test_regression_slash_daily_window():
    assert parse_notam_windows("2045/0100 DLY", BASE) == ["Ежедневно 20:45 - 01:00"]


def test_regression_single_day():
    assert parse_notam_windows("28 1223-1447", BASE) == ["Сентябрь 28, 12:23 - 14:47"]


def test_regression_comma_separated_days_use_base_rollover():
    # No explicit month token: days smaller than the base day (28) roll into
    # the next month via the base.day heuristic.
    assert parse_notam_windows("20 0334-0812, 21 0320-0758", BASE) == [
        "Октябрь 20, 03:34 - 08:12",
        "Октябрь 21, 03:20 - 07:58",
    ]


def test_regression_bare_window():
    assert parse_notam_windows("2245-0241", BASE) == ["22:45 - 02:41"]


def test_regression_empty():
    assert parse_notam_windows("", BASE) == []
    assert parse_notam_windows(None, BASE) == []
