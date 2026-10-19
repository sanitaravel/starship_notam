"""Choose the map extent: fit the NOTAM area, then zoom out until land shows.

Extents are ``[min_lon, max_lon, min_lat, max_lat]``; sizes are output
``(width, height)`` in pixels.
"""

from __future__ import annotations

import math

from src.core.logging import logger
from src.visualization.map_renderer.natural_earth import land_geometries

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


def extent_has_visible_land(extent, size) -> bool:
    """Return True if a usefully large landmass is visible within ``extent``.

    ``extent`` is ``[min_lon, max_lon, min_lat, max_lat]`` and ``size`` is the
    output ``(width, height)`` in pixels. Rather than accepting any intersection
    (which lets sub-pixel islands pass), this measures the on-screen footprint of
    the portion of each land geometry that falls inside the view and requires it
    to exceed ``MIN_LAND_PIXELS`` in either dimension.

    If land data is unavailable this returns ``True`` so we don't zoom out
    pointlessly.
    """
    geoms = land_geometries()
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


def expand_extent_until_land(extent, size):
    """Zoom the extent out around its center until a large landmass is visible.

    Keeps the NOTAM centered and preserves the aspect ratio by scaling both
    half-spans equally. Stops when a usefully large landmass is on screen (see
    :func:`extent_has_visible_land`), the half-spans exceed
    ``MAX_EXTENT_HALF_SPAN``, or the step cap is reached. Latitude is clamped to
    [-90, 90]; longitude is allowed to exceed +/-180 (Cartopy handles this).
    """
    try:
        if extent_has_visible_land(extent, size):
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
            if extent_has_visible_land(around_center(half_lon, half_lat), size):
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


def fit_extent(points, point, radius_value, size):
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
    return expand_extent_until_land(extent, size)
