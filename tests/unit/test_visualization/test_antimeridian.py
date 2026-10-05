"""Polygons crossing the 180° meridian must render as one compact area.

Regression test for fix-plan step 2 (NOTAMs 09/338, 09/339, 09/342, 09/343):
the FLT 14 ascent/reentry area runs 165°E -> 180° -> 145°W -> back to 170°E.
With longitudes kept in [-180, 180] the extent covered the whole globe, the
area was drawn the long way round, and the vertices were wrongly reordered.
"""

from __future__ import annotations

from starship_notam.parsers.coord_parser import parse_coords_from_text
from starship_notam.visualization.map_renderer import (
    _bounds_visible,
    _lon_shift_into,
    _normalize_polygon_order,
    _polygon_self_intersects,
    _unwrap_groups,
    _unwrap_longitudes,
)

FLT14_AREA = (
    "282800N1650000E TO 292500N1650000E TO 292500N1650300E TO 302600N1724100E "
    "TO 305700N1795900E TO 311100N1750000W TO 311700N1712900W TO 303300N1611500W "
    "TO 293700N1554000W TO 284900N1513500W TO 265300N1452600W TO 265000N1452800W "
    "TO 240300N1543200W TO 234600N1561100W TO 245200N1591900W TO 273800N1674900W "
    "TO 292500N1750000W TO 294500N1763500W TO 294800N1795900E TO 294100N1761400E "
    "TO 291300N1701000E"
)


def _lon_span(points):
    lons = [lon for _, lon in points]
    return max(lons) - min(lons)


def test_flt14_area_is_compact_after_unwrapping():
    raw = parse_coords_from_text(FLT14_AREA)
    assert _lon_span(raw) > 300  # the bug: looks like it spans the globe

    unwrapped = _unwrap_longitudes(raw)
    assert _lon_span(unwrapped) < 60
    assert min(lon for _, lon in unwrapped) >= 160
    assert max(lon for _, lon in unwrapped) <= 220


def test_flt14_area_is_not_reordered():
    unwrapped = _unwrap_longitudes(parse_coords_from_text(FLT14_AREA))

    assert not _polygon_self_intersects(unwrapped)
    assert _normalize_polygon_order(unwrapped) == unwrapped


def test_unwrap_leaves_ordinary_polygons_unchanged():
    pts = [(26.0, -97.2), (26.1, -97.0), (25.9, -96.9)]

    assert _unwrap_longitudes(pts) == pts


def test_groups_on_both_sides_of_antimeridian_share_a_frame():
    east = [(30.0, 178.0), (31.0, 179.0), (30.0, 179.5)]
    west = [(30.0, -179.5), (31.0, -179.0), (30.0, -178.0)]

    groups = _unwrap_groups([east, west])

    all_lons = [lon for g in groups for _, lon in g]
    assert max(all_lons) - min(all_lons) < 10


def test_labels_and_bounds_shift_into_unwrapped_extent():
    extent = [160.0, 220.0, 10.0, 45.0]

    # Hawaii (about 155°W) lies inside the unwrapped extent as 205°.
    assert _lon_shift_into(-155.0, extent[0], extent[1]) == 205.0
    assert _bounds_visible((-161.0, 18.0, -154.0, 23.0), extent)
    assert not _bounds_visible((0.0, 18.0, 10.0, 23.0), extent)
