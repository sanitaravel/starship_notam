"""Unit tests for :mod:`starship_notam.parsers.coord_parser`.

Covers DMS, decimal, and polygon coordinate parsing via
``parse_coords_from_text`` plus a determinism check (Requirement 3.6).

Imports only the parsers layer (Requirements 9.1, 9.4).
"""

from __future__ import annotations

import pytest

from starship_notam.parsers import parse_coords_from_text


# ---------------------------------------------------------------------------
# DMS parsing
# ---------------------------------------------------------------------------
def test_dms_with_seconds_returns_single_tuple():
    # 25°59'50"N 097°09'21"W
    result = parse_coords_from_text("255950N0970921W")

    assert isinstance(result, tuple)
    lat, lon = result
    assert abs(lat - 25.99722) < 1e-4
    assert abs(lon - (-97.15583)) < 1e-4


def test_dms_without_seconds_ddmm():
    # 25°59'N 097°09'W (4-digit lat DDMM, 5-digit lon DDDMM)
    result = parse_coords_from_text("2559N09709W")

    assert isinstance(result, tuple)
    lat, lon = result
    assert abs(lat - 25.98333) < 1e-4
    assert abs(lon - (-97.15)) < 1e-4


def test_dms_pair_with_separator():
    result = parse_coords_from_text("255950N, 0970921W")

    assert isinstance(result, tuple)
    lat, lon = result
    assert abs(lat - 25.99722) < 1e-4
    assert abs(lon - (-97.15583)) < 1e-4


# ---------------------------------------------------------------------------
# Decimal parsing
# ---------------------------------------------------------------------------
def test_decimal_comma_pair_single_tuple():
    result = parse_coords_from_text("25.99, -97.15")

    assert result == (25.99, -97.15)


def test_decimal_whitespace_pair():
    result = parse_coords_from_text("25.99 -97.15")

    assert result == (25.99, -97.15)


def test_decimal_multiple_pairs_returns_list():
    result = parse_coords_from_text("25.99, -97.15 26.08, -97.08")

    assert result == [(25.99, -97.15), (26.08, -97.08)]


# ---------------------------------------------------------------------------
# Polygon parsing (multiple DMS vertices)
# ---------------------------------------------------------------------------
def test_polygon_dms_chain_returns_list_of_tuples():
    raw = "255950N0970921W TO 260500N0970500W TO 255400N0964800W"
    result = parse_coords_from_text(raw)

    assert isinstance(result, list)
    assert len(result) == 3
    for point in result:
        assert isinstance(point, tuple)
        assert len(point) == 2

    # Spot-check the second and third vertices.
    assert abs(result[1][0] - 26.08333) < 1e-4
    assert abs(result[1][1] - (-97.08333)) < 1e-4
    assert abs(result[2][0] - 25.9) < 1e-4
    assert abs(result[2][1] - (-96.8)) < 1e-4


# ---------------------------------------------------------------------------
# No-match / empty inputs
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw", ["", "no coordinates here", "STARSHIP LAUNCH"])
def test_returns_none_when_no_coordinates(raw):
    assert parse_coords_from_text(raw) is None


# ---------------------------------------------------------------------------
# Determinism (Requirement 3.6)
# ---------------------------------------------------------------------------
def test_parse_coords_is_deterministic():
    raw = "255950N0970921W TO 260500N0970500W TO 255400N0964800W"
    assert parse_coords_from_text(raw) == parse_coords_from_text(raw)
