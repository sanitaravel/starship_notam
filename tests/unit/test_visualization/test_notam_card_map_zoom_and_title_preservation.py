"""Preservation property tests for the ``notam-card-map-zoom-and-title`` spec.

Property 2 (Preservation): for inputs where the bug condition does NOT hold, the
fix must not change behavior. This file captures the CURRENT (unfixed) behavior
of the map-extent pipeline and the Starship title summarizer as property-based
tests, so they pass now and must keep passing after task 3 lands the fix
(task 3.4 re-runs this exact file).

Observation-first methodology
-----------------------------
Rather than re-deriving the extent math, these tests observe the *real* extent
that :func:`render_map` feeds to Cartopy. We install a spy on
``GeoAxes.set_extent`` that records the extent and short-circuits the (expensive)
drawing, so every map assertion exercises genuine production code.

The assertions target the behaviors the design's Preservation Requirements say
must stay unchanged, expressed as fix-durable invariants rather than the exact
(currently over-zoomed) numbers:

* Land-adjacent geometry stays *fitted* — centered on the geometry, aspect
  corrected for cos(lat), and never ballooned to a near-global view.
* A point-with-radius stays fitted to its radius circle — centered on the point,
  with the radius circle fully inside the rendered extent.
* No parseable coordinates fall back to the exact default global extent.
* Every already-recognized summarization template returns the exact same line.
* Non-Starship text (no flight number) still returns ``None``.

The fix (task 3.1) relaxes ``MAP_EXTENT_SCALE`` and bounds the land-search
expansion; it does not move the geometry center, drop the aspect correction, or
change the no-coordinate fallback or any template line — so these invariants hold
before and after the fix.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**
"""

from __future__ import annotations

import logging
import math

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from starship_notam.visualization.map_renderer import MAP_H, MAP_W
from starship_notam.visualization.image_composer import extract_starship_template


MAP_SIZE = (MAP_W, MAP_H)
IMAGE_RATIO = float(MAP_W) / float(MAP_H)

# Cap on how large the rendered half-span may be relative to the tightly fitted
# geometry half-span for a LAND-ADJACENT NOTAM. On unfixed code the shared
# MAP_EXTENT_SCALE=2 doubles the footprint (land is adjacent so the land-search
# does not enlarge it further), so 2x is the observed factor; a little headroom
# leaves room for padding. This is the "stays fitted, not ballooned" invariant —
# the fix only shrinks this factor, so the bound keeps holding.
LAND_ADJACENT_MAX_ZOOM = 2.5


# ---------------------------------------------------------------------------
# Extent capture — spy on the real render_map -> ax.set_extent call.
# ---------------------------------------------------------------------------


def _capture_extent(coords, radius_nm=None):
    """Return the extent ``render_map`` passes to Cartopy for ``coords``.

    Installs a temporary spy on ``GeoAxes.set_extent`` that records the extent
    and raises a sentinel to skip the heavy feature drawing. This observes the
    genuine production extent pipeline (fit -> scale -> land expansion) without
    rendering a full tile.
    """
    import cartopy.mpl.geoaxes as ga

    captured: dict = {}
    sentinel = RuntimeError("STOP_AFTER_EXTENT")

    def spy(self, extents, crs=None):  # noqa: ANN001 - mirrors cartopy signature
        captured["extent"] = list(extents)
        raise sentinel

    original = ga.GeoAxes.set_extent
    # Silence the module's INFO logging so property runs stay quiet/fast.
    logging.disable(logging.CRITICAL)
    ga.GeoAxes.set_extent = spy
    try:
        from starship_notam.visualization.map_renderer import render_map

        try:
            render_map(coords, MAP_SIZE, radius_nm=radius_nm)
        except RuntimeError as exc:  # pragma: no cover - defensive
            if exc is not sentinel and "STOP_AFTER_EXTENT" not in str(exc):
                raise
    finally:
        ga.GeoAxes.set_extent = original
        logging.disable(logging.NOTSET)
        # render_map creates a matplotlib figure before set_extent; close all so
        # the many property-test iterations don't leak figures.
        try:
            import matplotlib.pyplot as plt

            plt.close("all")
        except Exception:
            pass

    return captured.get("extent")


def _center(extent):
    return (extent[0] + extent[1]) / 2.0, (extent[2] + extent[3]) / 2.0


def _half_spans(extent):
    return (extent[1] - extent[0]) / 2.0, (extent[3] - extent[2]) / 2.0


def _fitted_half_spans(coords):
    """Tight padded fit half-spans (pre-scale), mirroring render_map's fit block.

    Used only as a *reference* magnitude to bound the rendered extent; the
    rendered extent itself is captured from production, not computed here.
    """
    lats = [p[0] for p in coords]
    lons = [p[1] for p in coords]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)
    lat_pad = max((max_lat - min_lat) * 0.1, 0.1)
    lon_pad = max((max_lon - min_lon) * 0.1, 0.1)
    lat_span = max(max_lat - min_lat, 1e-6)
    lon_span = max(max_lon - min_lon, 1e-6)
    center_lat = (max_lat + min_lat) / 2.0
    cos_lat = max(math.cos(math.radians(center_lat)), 1e-6)
    adj_lon_span = lon_span * cos_lat
    current_ratio = adj_lon_span / lat_span
    if current_ratio < IMAGE_RATIO:
        needed_lon_span = (IMAGE_RATIO * lat_span) / cos_lat
        extra = (needed_lon_span - lon_span) / 2.0
        min_lon -= extra
        max_lon += extra
    elif current_ratio > IMAGE_RATIO:
        needed_lat_span = adj_lon_span / IMAGE_RATIO
        extra = (needed_lat_span - lat_span) / 2.0
        min_lat -= extra
        max_lat += extra
    fit_half_lon = ((max_lon + lon_pad) - (min_lon - lon_pad)) / 2.0
    fit_half_lat = ((max_lat + lat_pad) - (min_lat - lat_pad)) / 2.0
    return fit_half_lon, fit_half_lat


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Land-adjacent boxes: a small span sited on a real continental landmass so the
# land-visibility check succeeds on the fitted extent and the land-search does
# NOT enlarge it. Centers are drawn from mid-continent locations; spans are kept
# small (well under a degree up to a few degrees) to represent typical NOTAM
# footprints near land.
_LAND_CENTERS = st.sampled_from([
    (39.0, -98.0),   # central USA
    (26.0, -97.0),   # Texas Gulf coast / Starbase region
    (48.0, 2.0),     # France
    (52.0, 13.0),    # Germany
    (-15.0, -55.0),  # Brazil interior
    (-25.0, 134.0),  # central Australia
    (55.0, 60.0),    # western Russia
])


@st.composite
def land_adjacent_polygons(draw):
    center_lat, center_lon = draw(_LAND_CENTERS)
    half_lat = draw(st.floats(min_value=0.2, max_value=2.5))
    half_lon = draw(st.floats(min_value=0.2, max_value=2.5))
    return [
        (center_lat - half_lat, center_lon - half_lon),
        (center_lat - half_lat, center_lon + half_lon),
        (center_lat + half_lat, center_lon + half_lon),
        (center_lat + half_lat, center_lon - half_lon),
    ]


@st.composite
def radius_points(draw):
    # Points at varied latitudes (avoid the poles where cos(lat) collapses) with
    # small radii typical of a NOTAM danger circle.
    lat = draw(st.floats(min_value=-70.0, max_value=70.0))
    lon = draw(st.floats(min_value=-179.0, max_value=179.0))
    radius_nm = draw(st.floats(min_value=0.5, max_value=50.0))
    return (lat, lon), radius_nm


# NOTAM wordings that already match an existing template, paired with the exact
# summary line the UNFIXED code produces today (observed). The flight number is
# templated in for the branches that carry one.
def _flight(n):
    return str(n)


@st.composite
def recognized_template_cases(draw):
    """Yield (notam_text, expected_line) for every existing template branch."""
    flight = draw(st.integers(min_value=1, max_value=99))
    f = _flight(flight)
    branch = draw(st.sampled_from([
        "ground_hazard",
        "high_energy",
        "pacific_reentry",
        "ascent",
        "reentry_splashdown",
        "reentry_only",
        "debris_plural",
    ]))

    if branch == "ground_hazard":
        text = (
            "TEMPORARY FLIGHT RESTRICTION GROUND HAZARD WI AN AREA DEFINED AS "
            "CIRCLE RADIUS 2NM"
        )
        return text, "GROUND HAZARD AREA"

    if branch == "high_energy":
        text = "HIGH ENERGY TESTING BY SPACEX AT STARBASE TX"
        return text, "\u0412\u042b\u0421\u041e\u041a\u041e\u042d\u041d\u0415\u0420\u0413\u0415\u0422\u0418\u0427\u0415\u0421\u041a\u0418\u0415 \u0422\u0415\u0421\u0422\u0418\u0420\u041e\u0412\u0410\u041d\u0418\u042f"

    if branch == "pacific_reentry":
        # Branch 0c fires before flight extraction; no flight number required.
        text = (
            "RE-ENTRY OF SPACE VEHICLE OVER PACIFIC OCEAN WITH SPLASHDOWN"
        )
        return text, "\u0417\u041e\u041d\u0410 \u0412\u0425\u041e\u0414\u0410 \u0412 \u0410\u0422\u041c\u041e\u0421\u0424\u0415\u0420\u0423 \u0418 \u041f\u0420\u0418\u0412\u041e\u0414\u041d\u0415\u041d\u0418\u042f"

    if branch == "ascent":
        text = (
            f"AIRSPACE DCC DUE TO SPACEX STARSHIP FLT-{f} ASCENT STNR ALT "
            f"RESERVATION"
        )
        return text, (
            "\u0417\u0410\u041a\u0420\u042b\u0422\u0418\u0415 \u0412\u041e\u0417\u0414\u0423\u0428\u041d\u0415\u0413\u041e \u041f\u0420\u041e\u0421\u0422\u0420\u0410\u041d\u0421\u0422\u0412\u0410 "
            "\u0412 \u0421\u0412\u042f\u0417\u0418 \u0421 \u0417\u0410\u041f\u0423\u0421\u041a\u041e\u041c SPACEX STARSHIP "
            f"FLT-{f}"
        )

    if branch == "reentry_splashdown":
        text = (
            f"REENTRY OF SPACEX STARSHIP FLT-{f} WITH SPLASHDOWN IN THE "
            f"INDIAN OCEAN"
        )
        return text, (
            "\u0417\u041e\u041d\u0410 \u0412\u0425\u041e\u0414\u0410 \u0412 \u0410\u0422\u041c\u041e\u0421\u0424\u0415\u0420\u0423 \u0418 \u041f\u0420\u0418\u0412\u041e\u0414\u041d\u0415\u041d\u0418\u042f "
            "\u041a\u041e\u0421\u041c\u0418\u0427\u0415\u0421\u041a\u041e\u0413\u041e \u041a\u041e\u0420\u0410\u0411\u041b\u042f SPACEX STARSHIP "
            f"FLT-{f}"
        )

    if branch == "reentry_only":
        text = f"FOR REENTRY OF ROCKET SPACEX STARSHIP FLT-{f}"
        return text, (
            "\u0417\u041e\u041d\u0410 \u0412\u0425\u041e\u0414\u0410 \u0412 \u0410\u0422\u041c\u041e\u0421\u0424\u0415\u0420\u0423 "
            "\u041a\u041e\u0421\u041c\u0418\u0427\u0415\u0421\u041a\u041e\u0413\u041e \u041a\u041e\u0420\u0410\u0411\u041b\u042f SPACEX STARSHIP "
            f"FLT-{f}"
        )

    # debris_plural (branch 4). This is the wording family the fix EXTENDS (it
    # adds the singular "TEMPORARY DANGER AREA" etc.), but this already-matching
    # plural/"FALLING DEBRIS" wording must keep producing the same line.
    text = (
        f"TEMPORARY DANGER AREAS DUE LAUNCH OF SPACEX STARSHIP FLT-{f} "
        f"POSSIBILITY OF FALLING DEBRIS"
    )
    return text, (
        "\u0412\u041e\u0417\u041c\u041e\u0416\u041d\u041e\u0415 \u041f\u0410\u0414\u0415\u041d\u0418\u0415 \u041e\u0411\u041b\u041e\u041c\u041a\u041e\u0412 "
        "\u0412 \u0420\u0415\u0417\u0423\u041b\u042c\u0422\u0410\u0422\u0415 \u0417\u0410\u041f\u0423\u0421\u041a\u0410 SPACEX STARSHIP "
        f"FLT-{f}"
    )


# Non-Starship wordings: ordinary NOTAM text with no Starship flight number and
# none of the flight-free keyword triggers (ground hazard / high energy /
# pacific re-entry). These must return None today and after the fix.
_NON_STARSHIP_TEXTS = st.sampled_from([
    "RWY 09/27 CLOSED DUE TO MAINTENANCE WORK IN PROGRESS",
    "ILS RWY 04L GP U/S",
    "OBST CRANE ERECTED 1.2NM NE OF AERODROME 350FT AGL",
    "TWY B CLOSED BTN TWY A AND TWY C",
    "AD HOURS OF SERVICE CHANGED",
    "NAV VOR ABC OUT OF SERVICE FOR CALIBRATION",
    "MILITARY EXERCISE AREA ACTIVE FL100-FL250",
    "APRON LIGHTING UNSERVICEABLE DURING NIGHT OPERATIONS",
])


# ---------------------------------------------------------------------------
# 3.3 — No-coordinate fallback preservation.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("coords", [None, [], ()])
def test_no_coordinates_fall_back_to_global_extent(coords):
    """3.3: a NOTAM with no parseable coordinates renders the exact default
    global extent [-180, 180, -90, 90] today; the fix leaves this path
    untouched."""
    extent = _capture_extent(coords)
    assert extent == [-180, 180, -90, 90]


# ---------------------------------------------------------------------------
# 3.1 — Land-adjacent geometry stays fitted (centered, aspect-corrected,
#       never ballooned to a near-global view).
# ---------------------------------------------------------------------------


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(coords=land_adjacent_polygons())
def test_land_adjacent_polygon_stays_centered_and_fitted(coords):
    """3.1: for a polygon already next to a large landmass, the rendered extent
    stays centered on the geometry, keeps the cos(lat) aspect correction, and is
    not ballooned to a near-global view."""
    extent = _capture_extent(coords)
    assert extent is not None

    lats = [p[0] for p in coords]
    lons = [p[1] for p in coords]
    geom_center_lon = (min(lons) + max(lons)) / 2.0
    geom_center_lat = (min(lats) + max(lats)) / 2.0

    ext_center_lon, ext_center_lat = _center(extent)
    # Center preservation is exact today (scale and aspect correction are both
    # center-preserving) and the fix keeps it centered.
    assert ext_center_lon == pytest.approx(geom_center_lon, abs=1e-6)
    assert ext_center_lat == pytest.approx(geom_center_lat, abs=1e-6)

    # Aspect correction: the rendered extent's cos(lat)-adjusted width/height
    # ratio is near the image ratio. The correction runs before the scale and is
    # preserved by the fix; the fixed-degree padding (lat_pad/lon_pad, applied
    # after the correction) skews the ratio somewhat for tiny/elongated boxes, so
    # the observed envelope is roughly [0.9, 1.3] around the ~1.12 image ratio.
    # The point of the check is that the cos(lat) correction is applied at all
    # (not a raw 1:1 or a wildly off ratio), which the fix does not touch.
    half_lon, half_lat = _half_spans(extent)
    cos_lat = max(math.cos(math.radians(ext_center_lat)), 1e-6)
    adj_ratio = (half_lon * cos_lat) / half_lat
    assert 0.85 <= adj_ratio <= 1.4

    # Not ballooned: the fitted geometry stays the dominant feature. The
    # rendered half-spans stay within a small multiple of the tight fit rather
    # than growing to a near-global view.
    fit_half_lon, fit_half_lat = _fitted_half_spans(coords)
    assert half_lon <= LAND_ADJACENT_MAX_ZOOM * fit_half_lon
    assert half_lat <= LAND_ADJACENT_MAX_ZOOM * fit_half_lat
    # Sanity: a land-adjacent NOTAM is nowhere near the near-global half-span.
    assert half_lat < 60.0


# ---------------------------------------------------------------------------
# 3.2 — Point-with-radius stays fitted to its radius circle.
# ---------------------------------------------------------------------------


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(data=radius_points())
def test_point_with_radius_fits_the_circle(data):
    """3.2: a point-with-radius renders centered on the point with the radius
    circle fully inside the extent (aspect-corrected), as it does today."""
    (lat, lon), radius_nm = data
    extent = _capture_extent((lat, lon), radius_nm=radius_nm)
    assert extent is not None

    ext_center_lon, ext_center_lat = _center(extent)
    assert ext_center_lon == pytest.approx(lon, abs=1e-6)
    assert ext_center_lat == pytest.approx(lat, abs=1e-6)

    # The radius circle (radius in degrees of lat, and lon adjusted by cos(lat))
    # must sit fully inside the rendered extent.
    radius_deg_lat = radius_nm / 60.0
    cos_lat = max(math.cos(math.radians(lat)), 1e-6)
    radius_deg_lon = radius_nm / (60.0 * cos_lat)

    half_lon, half_lat = _half_spans(extent)
    assert half_lat >= radius_deg_lat - 1e-9
    assert half_lon >= radius_deg_lon - 1e-9

    # Aspect correction preserved for the point branch: the point branch applies
    # no post-correction padding, so the cos(lat)-adjusted ratio matches the
    # image ratio essentially exactly.
    adj_ratio = (half_lon * cos_lat) / half_lat
    assert adj_ratio == pytest.approx(IMAGE_RATIO, rel=0.05)


# ---------------------------------------------------------------------------
# 3.4 — Recognized templates produce the same summary line.
# ---------------------------------------------------------------------------


@settings(max_examples=60, deadline=None)
@given(case=recognized_template_cases())
def test_recognized_templates_unchanged(case):
    """3.4: every already-recognized Starship template returns the exact same
    summary line it produces today (the fix only adds keywords/fallback after
    these branches, so they are unaffected)."""
    text, expected = case
    assert extract_starship_template(text) == expected


# ---------------------------------------------------------------------------
# 3.5 — Non-Starship text still returns None (details derive from E/D).
# ---------------------------------------------------------------------------


@settings(max_examples=40, deadline=None)
@given(text=_NON_STARSHIP_TEXTS)
def test_non_starship_text_returns_none(text):
    """3.5: text with no Starship flight number (and none of the flight-free
    triggers) returns None today, so the card derives details from E/D. The fix
    only adds a fallback for recognized flights, so non-Starship text still
    returns None."""
    assert extract_starship_template(text) is None


@settings(max_examples=40, deadline=None)
@given(text=st.text(alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Zs")), max_size=60))
def test_random_text_without_flight_number_returns_none(text):
    """3.5 (broadened): random free text that contains neither a Starship flight
    number nor a flight-free trigger keyword returns None."""
    upper = " ".join(text.upper().split())
    triggers = [
        "SURFACE HAZARD OPERATIONS WI AN AREA DEFINED",
        "SURFACE HAZARD WI AN AREA DEFINED",
        "GROUND HAZARD WI AN AREA DEFINED",
        "HIGH ENERGY TESTING",
        "RE-ENTRY",
        "STARSHIP",
    ]
    # Only assert on inputs that clearly can't match any branch.
    if any(t in upper for t in triggers):
        return
    assert extract_starship_template(text) is None


# ---------------------------------------------------------------------------
# 3.6 — Cartography preserved: features still draw for an in-view geometry.
# ---------------------------------------------------------------------------


def test_map_renders_cartographic_features_for_land_geometry():
    """3.6: rendering a real map (no spy) for a land-adjacent NOTAM still
    produces an image tile of the expected size, exercising the full feature /
    graticule / label / marker drawing path unchanged by the fix."""
    from starship_notam.visualization.map_renderer import render_map

    coords = [
        (25.90, -97.20),
        (25.90, -96.20),
        (26.90, -96.20),
        (26.90, -97.20),
    ]
    img = render_map(coords, MAP_SIZE)
    assert img.size == MAP_SIZE
    assert img.mode == "RGBA"
