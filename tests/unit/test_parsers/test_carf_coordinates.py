"""CARF polygons must convert every coordinate precision correctly.

Regression test for fix-plan step 3: ``notam_parser`` had its own DMS
converter that treated the last four digits as minutes+seconds, so a
``DDMM``/``DDDMM`` token like ``1700N07140W`` became 0.28°N 1.19°W.
"""

from __future__ import annotations

import pytest

from starship_notam.parsers.notam_parser import parse_carf_message


def _polygon(chain: str):
    msg = (
        "!CARF 09/001 ZHU SPACEX OPS WI AN AREA DEFINED AS "
        f"{chain} SFC-UNL 2609281427-2609281833"
    )
    return [(p["lat"], p["lon"]) for p in parse_carf_message(msg)["polygon"]]


def test_degrees_minutes_tokens():
    pts = _polygon("1700N07140W TO 1626N07140W TO 1626N07300W")

    assert pts == [
        pytest.approx((17.0, -71 - 40 / 60)),
        pytest.approx((16 + 26 / 60, -71 - 40 / 60)),
        pytest.approx((16 + 26 / 60, -73.0)),
    ]


def test_degrees_minutes_seconds_tokens():
    pts = _polygon("260000N0955500W TO 255930N0954800W TO 282800N1650000E")

    assert pts == [
        pytest.approx((26.0, -(95 + 55 / 60))),
        pytest.approx((25 + 59 / 60 + 30 / 3600, -(95 + 48 / 60))),
        pytest.approx((28 + 28 / 60, 165.0)),
    ]
