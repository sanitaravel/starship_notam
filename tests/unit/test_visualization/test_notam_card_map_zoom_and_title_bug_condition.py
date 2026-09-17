"""Bug-condition exploration tests for the ``notam-card-map-zoom-and-title`` spec.

Property 1 (Bug Condition): an open-ocean NOTAM over-zooms and a Starship title
is not summarized. These tests encode the EXPECTED (post-fix) behavior, so on the
current UNFIXED code they are expected to FAIL — their failure is what confirms
the two bugs exist. They are permanent: tasks 3.3/3.4 re-run them to verify the
fix, at which point they must PASS.

Scope (per tasks.md "Scoped PBT Approach"): the properties are scoped to the two
concrete failing cases from NOTAM A1237/26 — the Tahiti-FIR polyline
(~19-24 deg S, 148-150 deg W) and the observed FLT-14 space-debris wording — so
the reproduction is deterministic.

Do NOT "fix" these tests or the production code from here; the orchestrator
sequences the fix in task 3.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4** (bug condition) and, once the fix
lands, **Requirements 2.1, 2.2, 2.3, 2.4** (Correctness Property 1).
"""

from __future__ import annotations

import math

import pytest

from starship_notam.visualization.map_renderer import (
    MAP_EXTENT_SCALE,
    MAP_H,
    MAP_W,
    _expand_extent_until_land,
)
from starship_notam.visualization.image_composer import extract_starship_template


# ---------------------------------------------------------------------------
# Concrete scoped inputs (from NOTAM A1237/26)
# ---------------------------------------------------------------------------

# Tahiti-FIR polyline near French Polynesia, roughly 19-24 deg S / 148-150 deg W.
# Coordinates are (lat, lon) tuples with west longitudes negative, matching the
# shape ``render_map`` receives for a polygon NOTAM.
TAHITI_FIR_POLYLINE = [
    (-19.85, -149.00),
    (-19.38, -148.82),
    (-24.97, -148.20),
    (-23.50, -150.10),
]

# A small polygon that already sits next to a large landmass (a ~1 deg box just
# off the Texas Gulf coast near Starbase). Used to isolate the MAP_EXTENT_SCALE
# doubling from the land-search ballooning.
LAND_ADJACENT_POLYGON = [
    (25.90, -97.20),
    (25.90, -96.20),
    (26.90, -96.20),
    (26.90, -97.20),
]

MAP_SIZE = (MAP_W, MAP_H)

# The exact card-overflowing wording observed on A1237/26: a recognized Starship
# flight number (FLT-14) with debris/danger wording that matches none of the
# existing classification branches, so the unfixed template returns None.
FLT14_DEBRIS_TEXT = (
    "TEMPORARY DANGER AREA DUE TO SPACE DEBRIS RETURN OF SPACEX STARSHIP "
    "FLT-14 IN TAHITI FIR WITHIN AN AREA BOUNDED BY FOLLOWING POINTS: "
    "1951S 14900W, 1923S 14849W, 2458S 14812W, 2350S 15006W"
)

# How much larger than the tightly fitted geometry the rendered view may grow and
# still keep the NOTAM the dominant, legible feature. A small multiple leaves room
# for padding/aspect correction while ruling out the near-global ballooning.
BOUNDED_ZOOM_MULTIPLE = 3.0


# ---------------------------------------------------------------------------
# Test helpers — replicate render_map's extent pipeline WITHOUT rendering.
#
# The fitting math below mirrors the polygon branch of ``render_map`` up to (but
# not including) the ``MAP_EXTENT_SCALE`` multiplication. The scale factor and the
# land-search expansion are driven through the REAL production constant
# (``MAP_EXTENT_SCALE``) and the REAL helper (``_expand_extent_until_land``), so
# these tests exercise genuine production behavior and will flip to passing once
# task 3.1 relaxes the scale and bounds the expansion.
# ---------------------------------------------------------------------------


def _fitted_extent(coords, size):
    """Return the aspect-corrected, padded fit for ``coords`` (pre-scale).

    Mirrors ``render_map``'s polygon branch before ``MAP_EXTENT_SCALE`` is
    applied and before ``_expand_extent_until_land`` runs.
    """
    lats = [p[0] for p in coords]
    lons = [p[1] for p in coords]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)
    lat_pad = max((max_lat - min_lat) * 0.1, 0.1)
    lon_pad = max((max_lon - min_lon) * 0.1, 0.1)
    map_w, map_h = size
    desired_ratio = float(map_w) / float(map_h)
    lat_span = max(max_lat - min_lat, 1e-6)
    lon_span = max(max_lon - min_lon, 1e-6)
    center_lat = (max_lat + min_lat) / 2.0
    cos_lat = max(math.cos(math.radians(center_lat)), 1e-6)
    adj_lon_span = lon_span * cos_lat
    current_ratio = adj_lon_span / lat_span
    if current_ratio < desired_ratio:
        needed_adj_lon = desired_ratio * lat_span
        needed_lon_span = needed_adj_lon / cos_lat
        extra = (needed_lon_span - lon_span) / 2.0
        min_lon -= extra
        max_lon += extra
    elif current_ratio > desired_ratio:
        needed_lat_span = adj_lon_span / desired_ratio
        extra = (needed_lat_span - lat_span) / 2.0
        min_lat -= extra
        max_lat += extra
    return [min_lon - lon_pad, max_lon + lon_pad, min_lat - lat_pad, max_lat + lat_pad]


def _apply_scale(extent, scale):
    """Apply ``render_map``'s center-preserving MAP_EXTENT_SCALE multiplication."""
    center_lon = (extent[0] + extent[1]) / 2.0
    center_lat = (extent[2] + extent[3]) / 2.0
    half_lon = (extent[1] - extent[0]) / 2.0 * scale
    half_lat = (extent[3] - extent[2]) / 2.0 * scale
    return [
        center_lon - half_lon,
        center_lon + half_lon,
        center_lat - half_lat,
        center_lat + half_lat,
    ]


def _rendered_extent(coords, size):
    """Return the extent ``render_map`` would actually use for ``coords``.

    Pipeline: fit -> MAP_EXTENT_SCALE -> land-visibility expansion, matching the
    order in ``render_map`` for a polygon with ``coords`` truthy.
    """
    fitted = _fitted_extent(coords, size)
    scaled = _apply_scale(fitted, MAP_EXTENT_SCALE)
    return _expand_extent_until_land(scaled, size)


def _half_spans(extent):
    return (extent[1] - extent[0]) / 2.0, (extent[3] - extent[2]) / 2.0


# ---------------------------------------------------------------------------
# Bug 1a — open-ocean polyline balloons to a near-global view.
# ---------------------------------------------------------------------------


def test_ocean_polyline_extent_stays_bounded_to_fitted_span():
    """Property 1a: the rendered view for the Tahiti-FIR polyline must stay a
    small multiple of the fitted geometry span (NOTAM dominant), not balloon to
    a near-global view.

    UNFIXED behavior (expected to FAIL): MAP_EXTENT_SCALE=2 then
    ``_expand_extent_until_land`` grow the half-spans to roughly 20x the fitted
    span (near-global, ~75 deg lon / ~69 deg lat half-span).
    """
    fitted = _fitted_extent(TAHITI_FIR_POLYLINE, MAP_SIZE)
    fit_half_lon, fit_half_lat = _half_spans(fitted)

    rendered = _rendered_extent(TAHITI_FIR_POLYLINE, MAP_SIZE)
    r_half_lon, r_half_lat = _half_spans(rendered)

    detail = (
        f"fitted half-span (lon={fit_half_lon:.3f}, lat={fit_half_lat:.3f}); "
        f"rendered half-span (lon={r_half_lon:.3f}, lat={r_half_lat:.3f}); "
        f"lon ratio={r_half_lon / fit_half_lon:.2f}x, "
        f"lat ratio={r_half_lat / fit_half_lat:.2f}x "
        f"(bound={BOUNDED_ZOOM_MULTIPLE}x)"
    )
    assert r_half_lon <= BOUNDED_ZOOM_MULTIPLE * fit_half_lon, detail
    assert r_half_lat <= BOUNDED_ZOOM_MULTIPLE * fit_half_lat, detail


# ---------------------------------------------------------------------------
# Bug 1 (scale) — MAP_EXTENT_SCALE doubles a land-adjacent polygon's footprint.
# ---------------------------------------------------------------------------


def test_land_adjacent_polygon_extent_not_scaled_out():
    """Property 1 (scale): a small land-adjacent polygon should render at its
    fitted half-span, so the NOTAM stays the dominant feature.

    UNFIXED behavior (expected to FAIL): the shared MAP_EXTENT_SCALE=2 doubles
    both half-spans, so the rendered half-span equals ~2x the fitted half-span.
    (Land is adjacent, so ``_expand_extent_until_land`` does not further enlarge
    it and the 2x scale is isolated.)
    """
    fitted = _fitted_extent(LAND_ADJACENT_POLYGON, MAP_SIZE)
    fit_half_lon, fit_half_lat = _half_spans(fitted)

    rendered = _rendered_extent(LAND_ADJACENT_POLYGON, MAP_SIZE)
    r_half_lon, r_half_lat = _half_spans(rendered)

    detail = (
        f"fitted half-span (lon={fit_half_lon:.3f}, lat={fit_half_lat:.3f}); "
        f"rendered half-span (lon={r_half_lon:.3f}, lat={r_half_lat:.3f}); "
        f"MAP_EXTENT_SCALE={MAP_EXTENT_SCALE}"
    )
    # After the fix the scale no longer doubles the footprint; a small tolerance
    # allows a light padding factor (e.g. 1.1) but rules out the 2x zoom-out.
    assert r_half_lon == pytest.approx(fit_half_lon, rel=0.2), detail
    assert r_half_lat == pytest.approx(fit_half_lat, rel=0.2), detail


# ---------------------------------------------------------------------------
# Bug 1b/2 — Starship title not summarized.
# ---------------------------------------------------------------------------


def test_flt14_debris_wording_is_summarized_to_concise_line():
    """Property 1b: a recognized Starship flight with unmatched wording must
    yield a concise, non-empty summary line (no coordinate list), so the card
    details are shortened rather than falling back to the raw NOTAM text.

    UNFIXED behavior (expected to FAIL): ``extract_starship_template`` returns
    None because the singular "TEMPORARY DANGER AREA" / "SPACE DEBRIS" /
    "DEBRIS RETURN" wording matches no classification branch.
    """
    result = extract_starship_template(FLT14_DEBRIS_TEXT)

    assert result is not None, (
        "extract_starship_template returned None for the FLT-14 space-debris "
        "wording; the card falls back to the full raw NOTAM text and overflows"
    )
    assert result.strip(), "summary line must be non-empty"
    # A concise summary must not carry the bounding-points coordinate list.
    assert "BOUNDED BY" not in result.upper(), (
        f"summary line still contains the coordinate list: {result!r}"
    )
    assert "1951S" not in result and "14900W" not in result, (
        f"summary line still contains raw coordinates: {result!r}"
    )
    # It should still reference the recognized flight number.
    assert "14" in result, f"summary line dropped the flight number: {result!r}"
