"""Cartopy/Matplotlib map rendering for NOTAM visualization.

This module renders a map image (as a :class:`PIL.Image.Image`) showing a NOTAM
polygon, circle, or point using Cartopy and Matplotlib.

The heavy plotting dependencies (``matplotlib``, ``cartopy``, ``shapely``) are
imported lazily inside :func:`render_map` so that importing this module does not
require those packages to be installed. This keeps the visualization layer
independently importable in test environments.

If Cartopy/Matplotlib/Shapely are unavailable when :func:`render_map` is called,
an :class:`ImportError` with a clear message identifying the missing dependency
is raised.
"""

import functools
import io
import math
from pathlib import Path

from PIL import Image

from starship_notam.core.logging import logger

# Right map fixed size (pixels). Kept here so callers may reference them.
MAP_W = 743
MAP_H = 662

# Map extent scale: values >1 slightly zoom out (makes NOTAM area appear smaller).
# Kept at 1.0 so the NOTAM geometry stays the dominant feature of the frame; the
# padding (lat_pad/lon_pad) and cos(lat) aspect-ratio correction applied before
# scaling still provide breathing room around the geometry.
MAP_EXTENT_SCALE = 1.0

# When a NOTAM sits in open ocean the initial extent may contain no meaningful
# land at all, leaving a featureless dark rectangle with no visual reference. In
# that case we progressively zoom out (keeping the NOTAM centered) until a
# usefully large landmass is visible or the extent grows past
# ``MAX_EXTENT_HALF_SPAN`` degrees.
LAND_ZOOM_OUT_FACTOR = 1.6  # per-step multiplier applied to the extent half-spans
LAND_ZOOM_OUT_MAX_STEPS = 10  # cap on the number of zoom-out iterations
MAX_EXTENT_HALF_SPAN = 90.0  # degrees; stop expanding once the view is near-global
# Bound the land-visibility zoom-out relative to the fitted geometry span so an
# open-ocean NOTAM (with no land nearby) stays fitted instead of ballooning to a
# near-global view chasing distant, unrelated continents. The land search may
# grow the extent up to this multiple of the fitted half-spans; if no usable
# land appears within that window, the fitted extent is returned unchanged.
#
# Kept deliberately small: a large multiple (previously 15x) let a polygon in
# the open South Pacific balloon its view all the way to continental South
# America, shrinking the NOTAM shape to a tiny sliver on a near-continental map.
# For open-ocean NOTAMs the polygon and graticule are the geographic reference,
# so we only allow a modest zoom-out to catch nearby land, not distant coasts.
LAND_ZOOM_OUT_MAX_SPAN_MULTIPLE = 3.0

# Geometries that already span at least this many degrees (in either dimension)
# are large enough to be self-referential on the map, so the land-visibility
# zoom-out is skipped entirely for them. This prevents big multi-hundred-mile
# hazard polygons from being zoomed out to chase distant continents.
LAND_ZOOM_OUT_SKIP_SPAN_DEG = 8.0
# Minimum on-screen footprint (in pixels) a landmass must occupy within the view
# to count as a usable visual reference. Tiny sub-pixel islands don't help, so we
# require land at least this large in either dimension. Tuned to match the
# ~60px threshold already used for country labelling.
MIN_LAND_PIXELS = 70.0

# Fonts directory lives at the project root, two levels up from this file:
#   starship_notam/visualization/map_renderer.py -> starship_notam/ -> project root
_FONTS_DIR = Path(__file__).resolve().parents[2] / "fonts"

# Cache of Natural Earth land geometries (prepared for fast intersection tests).
_LAND_GEOMS_CACHE = None


def _get_land_geometries():
    """Return a list of Natural Earth land geometries, loaded lazily and cached.

    Returns an empty list if the Natural Earth data or shapely cannot be loaded,
    so callers can degrade gracefully (treat as "no land information available").
    """
    global _LAND_GEOMS_CACHE
    if _LAND_GEOMS_CACHE is not None:
        return _LAND_GEOMS_CACHE
    geoms: list = []
    try:
        from cartopy.io import shapereader

        land_shp = shapereader.natural_earth(
            resolution="50m", category="physical", name="land"
        )
        reader = shapereader.Reader(land_shp)
        geoms = [rec.geometry for rec in reader.records() if rec.geometry is not None]
    except Exception:
        logger.exception("Could not load Natural Earth land geometries for land-visibility check")
        geoms = []
    _LAND_GEOMS_CACHE = geoms
    return geoms


@functools.lru_cache(maxsize=None)
def _natural_earth_records(resolution: str, category: str, name: str) -> tuple:
    """Return ``(attributes, geometry)`` pairs for a Natural Earth layer.

    Loaded once per process and cached; reading the shapefiles on every render
    was a large part of render time. A layer that cannot be loaded yields an
    empty tuple, which is cached too, so it is not re-downloaded each render.
    """
    try:
        from cartopy.io import shapereader

        path = shapereader.natural_earth(resolution=resolution, category=category, name=name)
        return tuple(
            (rec.attributes, rec.geometry)
            for rec in shapereader.Reader(path).records()
            if rec.geometry is not None
        )
    except Exception:
        logger.exception("Could not load Natural Earth layer %s/%s/%s", resolution, category, name)
        return ()


@functools.lru_cache(maxsize=None)
def _jetbrains_font_path() -> str | None:
    """Path of the bundled JetBrains Mono font, or None if it is missing."""
    if _FONTS_DIR.exists():
        for f in sorted(_FONTS_DIR.glob("*.ttf")):
            if "jetbrains" in f.name.lower():
                return str(f)
    return None


@functools.lru_cache(maxsize=None)
def _label_font(size: float | None):
    """Cached FontProperties for map labels (JetBrains Mono, else monospace).

    Matplotlib copies the properties into each Text, so sharing is safe.
    """
    import matplotlib.font_manager as fm

    path = _jetbrains_font_path()
    if path:
        return fm.FontProperties(fname=path, size=size)
    return fm.FontProperties(family="monospace", size=size)


def _extent_has_visible_land(extent, size) -> bool:
    """Return True if a usefully large landmass is visible within ``extent``.

    ``extent`` is ``[min_lon, max_lon, min_lat, max_lat]`` and ``size`` is the
    output ``(width, height)`` in pixels. Rather than accepting any intersection
    (which lets sub-pixel islands pass), this measures the on-screen footprint of
    the portion of each land geometry that falls inside the view and requires it
    to exceed ``MIN_LAND_PIXELS`` in either dimension.

    If land data is unavailable this returns ``True`` so we don't zoom out
    pointlessly.
    """
    geoms = _get_land_geometries()
    if not geoms:
        # No land data to test against; assume land may be present so we leave
        # the extent unchanged rather than zooming all the way out.
        return True
    try:
        from shapely.geometry import box

        min_lon, max_lon, min_lat, max_lat = extent[0], extent[1], extent[2], extent[3]
        lon_span = max(max_lon - min_lon, 1e-9)
        lat_span = max(max_lat - min_lat, 1e-9)
        px_per_lon = size[0] / lon_span
        px_per_lat = size[1] / lat_span
        # Land data is in [-180, 180]; an extent unwrapped past the antimeridian
        # is tested as up to three shifted views so land on either side counts.
        views = [
            box(min_lon + shift, min_lat, max_lon + shift, max_lat)
            for shift in (0.0, -360.0, 360.0)
            if max_lon + shift >= -180.0 and min_lon + shift <= 180.0
        ]
        for geom in geoms:
            for view in views:
                try:
                    if not geom.intersects(view):
                        continue
                    # Measure the visible portion, not the whole geometry, so a
                    # big country only just entering the frame still counts once
                    # enough of it is on screen.
                    clipped = geom.intersection(view)
                    if clipped.is_empty:
                        continue
                    cminx, cminy, cmaxx, cmaxy = clipped.bounds
                    pixel_w = (cmaxx - cminx) * px_per_lon
                    pixel_h = (cmaxy - cminy) * px_per_lat
                    if max(pixel_w, pixel_h) >= MIN_LAND_PIXELS:
                        return True
                except Exception:
                    continue
        return False
    except Exception:
        logger.exception("Land-visibility measurement failed")
        return True


def _expand_extent_until_land(extent, size):
    """Zoom the extent out around its center until a large landmass is visible.

    Keeps the NOTAM centered and preserves the aspect ratio by scaling both
    half-spans equally. Stops when a usefully large landmass is on screen (see
    :func:`_extent_has_visible_land`), the half-spans exceed
    ``MAX_EXTENT_HALF_SPAN``, or the step cap is reached. Latitude is clamped to
    [-90, 90]; longitude is allowed to exceed +/-180 (Cartopy handles this).
    """
    try:
        if _extent_has_visible_land(extent, size):
            return extent

        center_lon = (extent[0] + extent[1]) / 2.0
        center_lat = (extent[2] + extent[3]) / 2.0
        half_lon = (extent[1] - extent[0]) / 2.0
        half_lat = (extent[3] - extent[2]) / 2.0

        # Bound the search relative to the fitted geometry span so open-ocean
        # NOTAMs stay fitted instead of zooming out to reveal distant continents.
        max_half_lon = half_lon * LAND_ZOOM_OUT_MAX_SPAN_MULTIPLE
        max_half_lat = half_lat * LAND_ZOOM_OUT_MAX_SPAN_MULTIPLE

        def grown(half_lon, half_lat):
            """Half-spans one zoom step out, capped to the bounded window
            (relative to the fitted span, and never beyond near-global)."""
            return (
                min(half_lon * LAND_ZOOM_OUT_FACTOR, max_half_lon, MAX_EXTENT_HALF_SPAN),
                min(half_lat * LAND_ZOOM_OUT_FACTOR, max_half_lat, MAX_EXTENT_HALF_SPAN),
            )

        def around_center(half_lon, half_lat):
            return [
                center_lon - half_lon,
                center_lon + half_lon,
                max(center_lat - half_lat, -90.0),
                min(center_lat + half_lat, 90.0),
            ]

        for step in range(LAND_ZOOM_OUT_MAX_STEPS):
            half_lon, half_lat = grown(half_lon, half_lat)
            if _extent_has_visible_land(around_center(half_lon, half_lat), size):
                logger.info(
                    "Expanded map extent to reveal land after %d zoom-out step(s)", step + 1
                )
                # Go one step further so the land is not just at the edge.
                return around_center(*grown(half_lon, half_lat))
            # Once we've reached the bounded window without finding land, stop:
            # the NOTAM is genuinely in open ocean, so keep it fitted rather than
            # ballooning to a near-global view.
            if half_lon >= max_half_lon and half_lat >= max_half_lat:
                logger.info(
                    "No usable land within bounded window (%.1fx fitted span); "
                    "keeping map fitted to NOTAM geometry",
                    LAND_ZOOM_OUT_MAX_SPAN_MULTIPLE,
                )
                return extent
        logger.info(
            "Land-visibility zoom-out hit step cap without finding land; "
            "keeping map fitted to NOTAM geometry"
        )
        return extent
    except Exception:
        logger.exception("Failed to expand extent for land visibility; using original extent")
        return extent


def _nice_grid_step(span: float) -> float:
    """Pick a human-friendly graticule step (in degrees) for a given span.

    Aims for roughly 4-8 gridlines across the ``span`` by choosing from a set of
    "nice" steps (1-2-5 sequence, plus common angular values). Always returns a
    positive value.
    """
    if span <= 0:
        return 1.0
    # Target about 6 divisions across the visible span.
    raw = span / 6.0
    nice_steps = [
        0.01, 0.02, 0.05, 0.1, 0.2, 0.25, 0.5,
        1.0, 2.0, 5.0, 10.0, 15.0, 20.0, 30.0, 45.0, 60.0,
    ]
    for step in nice_steps:
        if step >= raw:
            return step
    return 90.0


def _frange(start: float, stop: float, step: float) -> list[float]:
    """Return evenly spaced values from ``start`` to ``stop`` inclusive.

    Values are rounded to a sensible precision so floating-point drift doesn't
    produce labels like ``-119.99999999``.
    """
    if step <= 0:
        return [start]
    vals: list[float] = []
    n = int(round((stop - start) / step))
    for i in range(n + 1):
        vals.append(round(start + i * step, 6))
    return vals


def _format_degrees(value: float) -> str:
    """Format an absolute degree magnitude, trimming trailing zeros.

    Examples: 120.0 -> "120", 0.5 -> "0.5", 29.25 -> "29.25".
    """
    mag = abs(value)
    if abs(mag - round(mag)) < 1e-6:
        return f"{int(round(mag))}"
    # Up to two decimals, then strip trailing zeros and a dangling dot.
    return f"{mag:.2f}".rstrip('0').rstrip('.')


def _format_lon(lon: float) -> str:
    """Format a longitude as e.g. ``120°W`` / ``75°E`` / ``0°``.

    Longitudes are normalized to the [-180, 180] range before formatting so
    zoomed-out views that wrap past +/-180 still show sensible values.
    """
    norm = ((lon + 180.0) % 360.0) - 180.0
    if abs(norm) < 1e-6 or abs(abs(norm) - 180.0) < 1e-6:
        return f"{_format_degrees(norm)}\u00b0"
    hemi = 'E' if norm > 0 else 'W'
    return f"{_format_degrees(norm)}\u00b0{hemi}"


def _format_lat(lat: float) -> str:
    """Format a latitude as e.g. ``29°S`` / ``5°N`` / ``0°``."""
    if abs(lat) < 1e-6:
        return "0\u00b0"
    hemi = 'N' if lat > 0 else 'S'
    return f"{_format_degrees(lat)}\u00b0{hemi}"


def _segments_intersect(p1, p2, p3, p4) -> bool:
    """Return True if open segment ``p1-p2`` properly crosses ``p3-p4``.

    Points are ``(lat, lon)`` tuples. Uses an orientation (CCW) test. Segments
    that merely share an endpoint are not treated as intersecting, so adjacent
    polygon edges don't count as crossings.
    """
    def ccw(a, b, c):
        return (c[0] - a[0]) * (b[1] - a[1]) - (b[0] - a[0]) * (c[1] - a[1])

    # Ignore pairs that share an endpoint (adjacent edges of the ring).
    if p1 in (p3, p4) or p2 in (p3, p4):
        return False

    d1 = ccw(p3, p4, p1)
    d2 = ccw(p3, p4, p2)
    d3 = ccw(p1, p2, p3)
    d4 = ccw(p1, p2, p4)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def _polygon_self_intersects(pts) -> bool:
    """Return True if the closed polygon through ``pts`` has crossing edges.

    ``pts`` is a list of ``(lat, lon)`` vertices (open ring; the closing edge
    back to the first point is tested implicitly). Fewer than 4 vertices can
    never self-intersect.
    """
    n = len(pts)
    if n < 4:
        return False
    edges = [(pts[i], pts[(i + 1) % n]) for i in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            a1, a2 = edges[i]
            b1, b2 = edges[j]
            if _segments_intersect(a1, a2, b1, b2):
                return True
    return False


def _order_by_centroid_angle(pts):
    """Return ``pts`` reordered counter-clockwise around their centroid.

    This untangles a vertex list whose given order self-intersects, producing a
    simple (non-self-crossing) polygon for convex and mildly-concave shapes,
    which covers NOTAM hazard areas. ``pts`` is a list of ``(lat, lon)`` tuples.
    """
    n = len(pts)
    cy = sum(p[0] for p in pts) / n  # centroid latitude
    cx = sum(p[1] for p in pts) / n  # centroid longitude
    return sorted(pts, key=lambda p: math.atan2(p[0] - cy, p[1] - cx))


def _is_multi_polygon(coords) -> bool:
    """True when ``coords`` is a list of coordinate groups (list-of-lists).

    A multi-polygon shape is ``[[(lat, lon), ...], [(lat, lon), ...], ...]`` -
    each inner list is one polygon. A single polygon (``[(lat, lon), ...]``) or
    a single point (``(lat, lon)``) returns False.
    """
    return (
        isinstance(coords, list)
        and len(coords) > 0
        and all(isinstance(g, list) and g for g in coords)
    )


def _unwrap_longitudes(pts):
    """Return ``pts`` with longitudes made continuous across the 180° meridian.

    NOTAM vertices are always given in [-180, 180], so a polygon that crosses
    the antimeridian jumps from e.g. 179°E to -175°W between two vertices.
    Whenever consecutive longitudes differ by more than 180° the following
    longitudes are shifted by ±360 so the ring stays continuous (179 -> 185).
    ``pts`` is a list of ``(lat, lon)`` tuples; other shapes are returned as-is.
    """
    if not isinstance(pts, list) or len(pts) < 2:
        return pts
    out = [tuple(pts[0])]
    offset = 0.0
    prev = pts[0][1]
    for lat, lon in pts[1:]:
        delta = lon - prev
        if delta > 180.0:
            offset -= 360.0
        elif delta < -180.0:
            offset += 360.0
        prev = lon
        out.append((lat, lon + offset))
    return out


def _unwrap_groups(groups):
    """Unwrap each polygon group and put all groups in the same ±360 frame.

    Each group is unwrapped on its own (see :func:`_unwrap_longitudes`), then
    shifted by a multiple of 360° so its mean longitude is within 180° of the
    first group's, keeping groups on either side of the antimeridian together.
    """
    unwrapped = [_unwrap_longitudes(list(g)) for g in groups if g]
    if not unwrapped:
        return unwrapped
    ref = sum(p[1] for p in unwrapped[0]) / len(unwrapped[0])
    aligned = [unwrapped[0]]
    for group in unwrapped[1:]:
        mean = sum(p[1] for p in group) / len(group)
        shift = 360.0 * round((ref - mean) / 360.0)
        aligned.append([(lat, lon + shift) for lat, lon in group])
    return aligned


def _lon_shift_into(lon: float, lo: float, hi: float) -> float | None:
    """Return ``lon`` shifted by a multiple of 360° to lie in ``[lo, hi]``.

    Used to place labels for [-180, 180] data on a map whose extent was
    unwrapped past ±180. Returns None when no shift lands inside the range.
    """
    for shift in (0.0, -360.0, 360.0):
        if lo <= lon + shift <= hi:
            return lon + shift
    return None


def _bounds_visible(bounds, extent) -> bool:
    """True when a ``(minx, miny, maxx, maxy)`` box overlaps ``extent``.

    ``extent`` is ``[min_lon, max_lon, min_lat, max_lat]`` and may extend past
    ±180, so the box is also tested shifted by ±360°.
    """
    minx, miny, maxx, maxy = bounds
    if maxy < extent[2] or miny > extent[3]:
        return False
    return any(
        maxx + shift >= extent[0] and minx + shift <= extent[1]
        for shift in (0.0, -360.0, 360.0)
    )


def _normalize_polygon_order(coords):
    """Return polygon vertices in a non-self-intersecting order.

    Only reorders when the vertices as given produce a self-intersecting
    ("bowtie") polygon; otherwise the original order is preserved verbatim so
    NOTAMs that already describe a simple polygon are drawn exactly as listed.

    ``coords`` is a list of ``(lat, lon)`` tuples. Returns a (possibly new) list.
    """
    try:
        if not isinstance(coords, list) or len(coords) < 4:
            return coords
        # Work on the distinct ring vertices, dropping an explicit closing point
        # (first == last) if present so it doesn't skew the centroid or the
        # intersection test.
        ring = coords[:-1] if len(coords) > 1 and coords[0] == coords[-1] else list(coords)
        if len(ring) < 4:
            return coords
        if not _polygon_self_intersects(ring):
            return coords
        reordered = _order_by_centroid_angle(ring)
        if _polygon_self_intersects(reordered):
            # Reordering didn't help (unusual concave case); keep original.
            logger.info(
                "Polygon self-intersects but centroid-angle reorder did not "
                "resolve it; keeping original vertex order"
            )
            return coords
        logger.info(
            "Polygon vertices self-intersected in listed order; reordered by "
            "centroid angle to form a simple polygon"
        )
        return reordered
    except Exception:
        logger.exception("Failed to normalize polygon vertex order; using original")
        return coords


# Fill/outline used for every NOTAM area (polygon or circle).
_AREA_STYLE = dict(
    facecolor=(207 / 255, 0, 0, 0.18),
    edgecolor=(207 / 255, 0, 0, 0.95),
    linewidth=1.6,
)
# Place-name labels: lighter than the ocean (#262626 -> #858585).
_LABEL_COLOR = "#858585"
STARBASE_LAT = 25.9896
STARBASE_LON = -97.1849


def _polygon_groups(coords):
    """Return ``coords`` as a list of polygon groups, or None if not a polygon.

    A multi-area NOTAM (list of lists) gives one group per area; a single
    polygon (list of ``(lat, lon)``) is treated as a list of one. Longitudes
    are unwrapped first so a polygon crossing the 180° meridian is one
    continuous ring (e.g. 165..215 instead of jumping 179 -> -175); the
    wrap-around edges would otherwise look like self-intersections, blow the
    extent up to the whole globe, and draw the area the long way round. Then
    vertices listed out of geometric order (a "bowtie") are untangled.
    """
    if _is_multi_polygon(coords):
        groups = coords
    elif isinstance(coords, list) and coords:
        groups = [coords]
    else:
        return None
    return [_normalize_polygon_order(g) for g in _unwrap_groups(groups)]


def _parse_radius(radius_nm) -> float | None:
    """Return ``radius_nm`` as a positive float, or None."""
    try:
        if radius_nm is None:
            return None
        value = float(str(radius_nm).strip())
    except Exception:
        return None
    return value if value > 0 else None


def _polygon_extent(points, size):
    """Padded extent around ``points``, widened to the image aspect ratio."""
    logger.info("Rendering polygon with %d points on map", len(points))
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)
    lat_pad = max((max_lat - min_lat) * 0.1, 0.1)
    lon_pad = max((max_lon - min_lon) * 0.1, 0.1)
    # Adjust extent so the geographic box matches the image aspect ratio
    map_w, map_h = size
    desired_ratio = float(map_w) / float(map_h)
    lat_span = max(max_lat - min_lat, 1e-6)
    lon_span = max(max_lon - min_lon, 1e-6)
    center_lat = (max_lat + min_lat) / 2.0
    cos_lat = max(math.cos(math.radians(center_lat)), 1e-6)
    # approximate longitudinal span in latitude-equivalent units
    adj_lon_span = lon_span * cos_lat
    current_ratio = adj_lon_span / lat_span
    if current_ratio < desired_ratio:
        # need wider longitudinal span
        needed_adj_lon = desired_ratio * lat_span
        needed_lon_span = needed_adj_lon / cos_lat
        extra = (needed_lon_span - lon_span) / 2.0
        min_lon -= extra
        max_lon += extra
    elif current_ratio > desired_ratio:
        # need taller latitudinal span
        needed_lat_span = adj_lon_span / desired_ratio
        extra = (needed_lat_span - lat_span) / 2.0
        min_lat -= extra
        max_lat += extra
    extent = [min_lon - lon_pad, max_lon + lon_pad, min_lat - lat_pad, max_lat + lat_pad]
    # Apply the global extent scale around the centre (zooms out when > 1).
    center_lon = (extent[0] + extent[1]) / 2.0
    center_lat = (extent[2] + extent[3]) / 2.0
    half_lon = (extent[1] - extent[0]) / 2.0
    half_lat = (extent[3] - extent[2]) / 2.0
    half_lon *= MAP_EXTENT_SCALE
    half_lat *= MAP_EXTENT_SCALE
    return [center_lon - half_lon, center_lon + half_lon, center_lat - half_lat, center_lat + half_lat]


def _point_extent(point, radius_value, size):
    """Extent around a point (or circle of ``radius_value`` NM) at the image aspect ratio."""
    lat, lon = point
    logger.info("Rendering single point on map at lat=%.4f, lon=%.4f", lat, lon)
    cos_lat = max(math.cos(math.radians(lat)), 1e-6)
    if radius_value is not None:
        base_half_lat = max(radius_value / 60.0, 0.15)
        base_half_lon = max(radius_value / (60.0 * cos_lat), 0.15)
    else:
        # base half-spans (degrees)
        base_half_lat = 1.0
        base_half_lon = 1.0
    map_w, map_h = size
    desired_ratio = float(map_w) / float(map_h)
    adj_lon_span = (base_half_lon * 2.0) * cos_lat
    lat_span = (base_half_lat * 2.0)
    current_ratio = adj_lon_span / lat_span if lat_span > 0 else 1.0
    if current_ratio < desired_ratio:
        needed_adj_lon = desired_ratio * lat_span
        needed_lon_span = needed_adj_lon / cos_lat
        half_lon = needed_lon_span / 2.0
        half_lat = base_half_lat
    else:
        needed_lat_span = adj_lon_span / desired_ratio
        half_lat = needed_lat_span / 2.0
        half_lon = base_half_lon
    half_lon *= MAP_EXTENT_SCALE
    half_lat *= MAP_EXTENT_SCALE
    return [lon - half_lon, lon + half_lon, lat - half_lat, lat + half_lat]


def _fit_extent(points, point, radius_value, size):
    """Return the map extent ``[min_lon, max_lon, min_lat, max_lat]``.

    Fits ``points`` (all polygon vertices) or the single ``point``, then makes
    sure some land is visible for geographic reference: NOTAMs in the open
    ocean can otherwise produce a featureless dark rectangle, so the view is
    zoomed out (keeping the NOTAM centred) until land enters it. That step is
    skipped for geometries that already span a large area: a big polygon is
    its own reference, and zooming out to reach a distant coast would shrink
    it to an unreadable sliver. With neither, the whole globe is shown.
    """
    if points:
        extent = _polygon_extent(points, size)
        lats = [p[0] for p in points]
        lons = [p[1] for p in points]
        geom_span_deg = max(max(lats) - min(lats), max(lons) - min(lons))
    elif point:
        extent = _point_extent(point, radius_value, size)
        geom_span_deg = 0.0
    else:
        logger.info("No valid coordinates provided, using default global extent")
        return [-180, 180, -90, 90]

    if geom_span_deg >= LAND_ZOOM_OUT_SKIP_SPAN_DEG:
        logger.info(
            "Geometry spans %.1f deg (>= %.1f); skipping land-visibility zoom-out",
            geom_span_deg, LAND_ZOOM_OUT_SKIP_SPAN_DEG,
        )
        return extent
    return _expand_extent_until_land(extent, size)


def _add_base_layers(ax, cfeature) -> None:
    """Draw ocean, lakes, land, coastlines and country borders (dark theme)."""
    try:
        # Use requested ocean and land colors: ocean=#262626, land=#090909
        ax.add_feature(cfeature.OCEAN.with_scale('50m'), facecolor='#262626')
        # Render inland lakes using the same ocean color to match dark theme
        ax.add_feature(cfeature.LAKES.with_scale('50m'), facecolor='#262626')
        ax.add_feature(cfeature.LAND.with_scale('50m'), facecolor='#090909')
        ax.add_feature(cfeature.COASTLINE.with_scale('50m'), edgecolor='#2b2b2b', linewidth=0.5)
        # Draw province (admin-1) and country (admin-0) boundaries.
        # Countries are drawn thicker than provinces to improve readability.
        try:
            admin0 = cfeature.NaturalEarthFeature(category='cultural', name='admin_0_boundary_lines_land', scale='50m', facecolor='none')
            ax.add_feature(admin0, edgecolor='#3b3b3b', linewidth=1.2, zorder=7)
        except Exception:
            # If NaturalEarth admin layers aren't available, fall back to BORDERS
            ax.add_feature(cfeature.BORDERS.with_scale('50m'), edgecolor='#3b3b3b', linewidth=1.0)
    except Exception:
        # some cartopy installations may not have naturalearth data available; fall back to coastlines and lakes if possible
        ax.coastlines(resolution='110m', color='#2b2b2b', linewidth=0.5)
        try:
            ax.add_feature(cfeature.LAKES.with_scale('110m'), facecolor='#262626')
        except Exception:
            pass


def _draw_graticule(ax, proj, extent, central_lon: float) -> None:
    """Draw latitude/longitude lines sized to the extent, with inline labels.

    Steps adapt so lines stay legible from close-in NOTAMs to near-global
    views. Labels are drawn *inside* the map area rather than on the axes
    edges, because the map is rendered full-bleed (axes fill the whole
    figure) so edge labels would be clipped.
    """
    try:
        import matplotlib.ticker as mticker
        import matplotlib.patheffects as _pe

        lon_span = max(extent[1] - extent[0], 1e-6)
        lat_span = max(extent[3] - extent[2], 1e-6)
        lon_step = _nice_grid_step(lon_span)
        lat_step = _nice_grid_step(lat_span)

        # Compute tick positions covering the visible extent, snapped to
        # multiples of the chosen step.
        lon_start = math.floor(extent[0] / lon_step) * lon_step
        lon_end = math.ceil(extent[1] / lon_step) * lon_step
        lat_start = math.floor(extent[2] / lat_step) * lat_step
        lat_end = math.ceil(extent[3] / lat_step) * lat_step
        lon_ticks = _frange(lon_start, lon_end, lon_step)
        lat_ticks = [t for t in _frange(lat_start, lat_end, lat_step) if -90.0 <= t <= 90.0]

        # Draw the grid lines themselves (no edge labels).
        gl = ax.gridlines(
            crs=proj,
            draw_labels=False,
            linewidth=0.5,
            color='#3a3a3a',
            alpha=0.9,
            linestyle=(0, (4, 4)),
            zorder=6,
        )
        gl.xlocator = mticker.FixedLocator([t - central_lon for t in lon_ticks])
        gl.ylocator = mticker.FixedLocator(lat_ticks)

        # Subtle dark outline keeps labels readable over land or the NOTAM shape.
        stroke = [_pe.withStroke(linewidth=2.0, foreground='#1c1c1c')]
        # Inset labels slightly from the edges so they don't touch the border.
        lon_inset = extent[0] + lon_span * 0.012  # left inset for latitude labels
        lat_inset = extent[2] + lat_span * 0.018  # bottom inset for longitude labels
        text_kwargs = dict(
            transform=proj,
            color='#8a8a8a',
            fontsize=8,
            zorder=9,
            clip_on=True,
            path_effects=stroke,
        )
        if _jetbrains_font_path() is not None:
            text_kwargs['fontproperties'] = _label_font(None)

        # Longitude labels: one per vertical line, along the bottom edge.
        for lon_v in lon_ticks:
            if extent[0] <= lon_v <= extent[1]:
                ax.text(
                    lon_v - central_lon, lat_inset, _format_lon(lon_v),
                    ha='center', va='bottom', **text_kwargs,
                )
        # Latitude labels: one per horizontal line, along the left edge.
        for lat_v in lat_ticks:
            if extent[2] <= lat_v <= extent[3]:
                ax.text(
                    lon_inset - central_lon, lat_v, _format_lat(lat_v),
                    ha='left', va='center', **text_kwargs,
                )
    except Exception:
        logger.exception("Failed to draw coordinate gridlines")


def _label_layer(
    ax, proj, extent, size, central_lon, records, name_keys, min_pixels,
    font_size, zorder, bold=False,
) -> None:
    """Label each visible, large-enough feature of a layer at a point inside it.

    ``records`` are ``(attributes, geometry)`` pairs; the name is the first
    non-empty of ``name_keys``. Features smaller than ``min_pixels`` on screen
    are skipped to avoid clutter, and ``font_size`` maps that pixel size to a
    font size.
    """
    import matplotlib.patheffects as patheffects

    ext_min_lon, ext_max_lon, ext_min_lat, ext_max_lat = extent
    ext_lon_span = max(ext_max_lon - ext_min_lon, 1e-6)
    ext_lat_span = max(ext_max_lat - ext_min_lat, 1e-6)
    # small margin so labels don't sit right on the border
    lon_margin = ext_lon_span * 0.03
    lat_margin = ext_lat_span * 0.03
    extra = {'fontweight': 'bold'} if bold else {}
    for attrs, geom in records:
        try:
            name = next((attrs.get(k) for k in name_keys if attrs.get(k)), None)
            if not name:
                continue
            minx, miny, maxx, maxy = geom.bounds
            # quick intersection test against current extent
            if not _bounds_visible((minx, miny, maxx, maxy), extent):
                continue
            # approximate pixel span of this feature within current extent
            pixel_w = (maxx - minx) / ext_lon_span * size[0]
            pixel_h = (maxy - miny) / ext_lat_span * size[1]
            maxpix = max(pixel_w, pixel_h)
            if maxpix < min_pixels:
                continue
            # choose a point guaranteed to lie within the geometry for label placement
            try:
                label_pt = geom.representative_point()
            except Exception:
                label_pt = geom.centroid
            lx = _lon_shift_into(label_pt.x, ext_min_lon + lon_margin, ext_max_lon - lon_margin)
            ly = label_pt.y
            # ensure label point is comfortably inside the visible extent
            if lx is None or not (ext_min_lat + lat_margin <= ly <= ext_max_lat - lat_margin):
                continue
            txt = ax.text(lx - central_lon, ly, name, fontproperties=_label_font(font_size(maxpix)), color=_LABEL_COLOR, transform=proj, ha='center', va='center', zorder=zorder, clip_on=True, **extra)
            txt.set_path_effects([patheffects.withStroke(linewidth=2, foreground='black')])
            try:
                txt.set_clip_path(ax.patch)
            except Exception:
                pass
        except Exception:
            # continue labeling other features even if one fails
            continue


def _draw_starbase(ax, proj, extent, size, central_lon) -> None:
    """Draw the Starbase, TX marker and label when it is inside the extent."""
    import matplotlib.patheffects as patheffects

    ext_min_lon, ext_max_lon, ext_min_lat, ext_max_lat = extent
    star_lon = _lon_shift_into(STARBASE_LON, ext_min_lon, ext_max_lon)
    if star_lon is None or not ext_min_lat <= STARBASE_LAT <= ext_max_lat:
        return
    x = star_lon - central_lon
    try:
        ax.scatter([x], [STARBASE_LAT], s=70, color='#FF8014', edgecolors='black', linewidths=0.8, transform=proj, zorder=13)
    except Exception:
        try:
            ax.plot(x, STARBASE_LAT, marker='o', markersize=6, color='#FF8014', transform=proj, zorder=13)
        except Exception:
            pass
    # label offset a bit to the right and up
    try:
        dx = max(ext_max_lon - ext_min_lon, 1e-6) * 0.02
        dy = max(ext_max_lat - ext_min_lat, 1e-6) * 0.01
        sfontsize = max(8, min(12, int(min(size) / 60)))
        stxt = ax.text(x + dx, STARBASE_LAT + dy, 'Starbase, TX', fontproperties=_label_font(sfontsize), color=_LABEL_COLOR, transform=proj, ha='left', va='bottom', zorder=13, clip_on=True)
        stxt.set_path_effects([patheffects.withStroke(linewidth=1.8, foreground='black')])
        try:
            stxt.set_clip_path(ax.patch)
        except Exception:
            pass
    except Exception:
        pass


def _draw_labels(ax, proj, extent, size, central_lon) -> None:
    """Label visible countries and large water bodies, and mark Starbase."""
    try:
        # Countries from Natural Earth admin_0_countries.
        _label_layer(
            ax, proj, extent, size, central_lon,
            _natural_earth_records('50m', 'cultural', 'admin_0_countries'),
            ('ADMIN', 'NAME', 'NAME_LONG', 'SOVEREIGNT'),
            min_pixels=60,
            font_size=lambda px: max(7, min(12, int(px / 18))),
            zorder=11,
            bold=True,
        )
        # Large named water bodies. Only the 50m layers are used, matching the
        # rest of the map; also loading 10m labelled the same lakes twice.
        for layer in ('ocean', 'lakes'):
            _label_layer(
                ax, proj, extent, size, central_lon,
                _natural_earth_records('50m', 'physical', layer),
                ('name', 'NAME', 'NAME_EN', 'NAME_LONG', 'NAME_HI'),
                min_pixels=60,
                font_size=lambda px: max(8, min(18, int(px / 22))),
                zorder=10,
            )
        try:
            _draw_starbase(ax, proj, extent, size, central_lon)
        except Exception:
            logger.debug('Starbase marker placement failed')
    except Exception:
        # drawing labels is non-critical; do not fail the whole rendering if shapereader/patheffects unavailable
        logger.debug("Shapereader or patheffects not available; skipping labels")


def _draw_geometry(ax, proj, polygon_groups, point, radius_value, central_lon) -> None:
    """Draw each NOTAM polygon, or the circle around ``point``.

    A point without a radius is not drawn (no centre marker, by request).
    """
    from shapely.geometry import Polygon

    if polygon_groups is not None:
        # Each area (e.g. two AND-separated DRA boundaries) is its own polygon
        # so they stay visually separate.
        logger.info("Drawing %d polygon group(s) on cartopy map", len(polygon_groups))
        for gi, group in enumerate(polygon_groups):
            if not group:
                continue
            try:
                poly = Polygon([(lon - central_lon, lat) for lat, lon in group])
                ax.add_geometries([poly], crs=proj, **_AREA_STYLE)
            except Exception:
                logger.exception("Failed to draw polygon group %d on cartopy map", gi)
    elif point and radius_value is not None:
        lat, lon = point
        logger.info("Drawing circle on cartopy map with radius %.2f NM", radius_value)
        lat_deg = radius_value / 60.0
        cos_lat = max(math.cos(math.radians(lat)), 1e-6)
        lon_deg = radius_value / (60.0 * cos_lat)
        circle_pts = []
        for i in range(72):
            ang = 2.0 * math.pi * (i / 72.0)
            p_lat = lat + lat_deg * math.sin(ang)
            p_lon = lon + lon_deg * math.cos(ang)
            circle_pts.append((p_lon - central_lon, p_lat))
        try:
            ax.add_geometries([Polygon(circle_pts)], crs=proj, **_AREA_STYLE)
        except Exception:
            logger.exception("Failed to draw circle geometry on cartopy map")
    elif point:
        logger.info("Drawing point on cartopy map")


def render_map(coords, size: tuple[int, int] = (MAP_W, MAP_H), radius_nm: float | None = None) -> "Image.Image":
    """Render a map image (PIL.Image) showing the given coords polygon or point using Cartopy.

    Returns an RGBA PIL Image of exact ``size``.

    Parameters
    ----------
    coords :
        A list of ``(lat, lon)`` tuples describing a polygon, a list of such
        lists (one polygon per area), a single ``(lat, lon)`` tuple describing
        a point, or ``None``/empty for a default global extent.
    size : tuple[int, int]
        The output image size in pixels as ``(width, height)``.
    radius_nm : float or None
        Optional radius in nautical miles used to draw a circle around a point.

    Raises
    ------
    ImportError
        If Cartopy, Matplotlib, or Shapely are not installed when this function
        is called.
    """
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import cartopy.crs as ccrs
        import cartopy.feature as cfeature
        import shapely.geometry  # noqa: F401 - fail early if shapely is missing
    except Exception as e:
        logger.exception("Cartopy/Matplotlib not available: %s", e)
        raise ImportError(
            "cartopy and matplotlib are required for map rendering; "
            "install project dependencies via 'pip install .'"
        ) from e

    polygon_groups = _polygon_groups(coords)
    point = coords if isinstance(coords, tuple) and coords else None
    radius_value = _parse_radius(radius_nm)
    points = [pt for g in polygon_groups for pt in g] if polygon_groups else None
    extent = _fit_extent(points, point, radius_value, size)

    # When the (unwrapped) extent leaves [-180, 180], centre the projection on
    # it so the area is drawn in one piece. All geometry and text is then
    # placed in the axes' own CRS, with x = lon - central_lon. For every other
    # NOTAM central_lon is 0 and this is identical to plain PlateCarree.
    central_lon = 0.0
    if extent[0] < -180.0 or extent[1] > 180.0:
        central_lon = (extent[0] + extent[1]) / 2.0
        logger.info("Extent crosses the antimeridian; centring map on %.1f deg", central_lon)
    proj = ccrs.PlateCarree(central_longitude=central_lon)

    fig_dpi = 100
    fig_w = size[0] / fig_dpi
    fig_h = size[1] / fig_dpi
    logger.info("Creating map figure with size %dx%d pixels (%.2fx%.2f inches at %d DPI)", size[0], size[1], fig_w, fig_h, fig_dpi)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=fig_dpi, subplot_kw=dict(projection=proj))
    # Match figure and axes background to the canvas ocean color (#262626)
    fig.patch.set_facecolor('#262626')
    ax.set_facecolor('#262626')
    # Some GeoAxes implementations may not have outline_patch; guard access
    try:
        if hasattr(ax, 'outline_patch') and ax.outline_patch is not None:
            ax.outline_patch.set_visible(False)
    except Exception:
        logger.exception("Failed to hide axes outline, map may have unexpected border")

    ax.set_extent([extent[0] - central_lon, extent[1] - central_lon, extent[2], extent[3]], crs=proj)

    # Cartopy GeoAxes enforce an equal ('box') aspect by default, which
    # letterboxes the map inside the axes and leaves dark bands at the top and
    # bottom of the fixed-size figure. Our extent is already aspect-corrected to
    # the image ratio (using a cos(lat) adjustment), so switch to 'auto' aspect
    # to let the data stretch and fill the whole box with negligible distortion.
    try:
        ax.set_aspect('auto')
    except Exception:
        logger.exception("Failed to set axes aspect to 'auto'; map may be letterboxed")

    _add_base_layers(ax, cfeature)
    _draw_graticule(ax, proj, extent, central_lon)
    _draw_labels(ax, proj, extent, size, central_lon)
    _draw_geometry(ax, proj, polygon_groups, point, radius_value, central_lon)

    # remove axes and padding
    ax.set_xticks([])
    ax.set_yticks([])
    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)

    # Force the GeoAxes to cover the entire figure area so the saved
    # PNG occupies the full requested pixel rectangle. Save with an
    # opaque facecolor so there aren't transparent bands at the top/bottom.
    try:
        ax.set_position([0, 0, 1, 1])
    except Exception:
        logger.exception("Failed to set axes position, map may have unexpected padding")

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=fig_dpi, facecolor=fig.get_facecolor(), transparent=False)
    plt.close(fig)
    buf.seek(0)
    map_img = Image.open(buf).convert('RGBA')
    # ensure exact size
    if map_img.size != size:
        map_img = map_img.resize(size, Image.LANCZOS)
    return map_img
