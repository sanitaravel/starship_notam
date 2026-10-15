"""NOTAM area geometry: polygon groups, antimeridian unwrapping, bowtie untangling.

Points are ``(lat, lon)`` tuples throughout. Pure Python; no plotting imports.
"""

from __future__ import annotations

import math

from starship_notam.core.logging import logger


def segments_intersect(p1, p2, p3, p4) -> bool:
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


def polygon_self_intersects(pts) -> bool:
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
            if segments_intersect(a1, a2, b1, b2):
                return True
    return False


def order_by_centroid_angle(pts):
    """Return ``pts`` reordered counter-clockwise around their centroid.

    This untangles a vertex list whose given order self-intersects, producing a
    simple (non-self-crossing) polygon for convex and mildly-concave shapes,
    which covers NOTAM hazard areas. ``pts`` is a list of ``(lat, lon)`` tuples.
    """
    n = len(pts)
    cy = sum(p[0] for p in pts) / n  # centroid latitude
    cx = sum(p[1] for p in pts) / n  # centroid longitude
    return sorted(pts, key=lambda p: math.atan2(p[0] - cy, p[1] - cx))


def is_multi_polygon(coords) -> bool:
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


def unwrap_longitudes(pts):
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


def unwrap_groups(groups):
    """Unwrap each polygon group and put all groups in the same ±360 frame.

    Each group is unwrapped on its own (see :func:`unwrap_longitudes`), then
    shifted by a multiple of 360° so its mean longitude is within 180° of the
    first group's, keeping groups on either side of the antimeridian together.
    """
    unwrapped = [unwrap_longitudes(list(g)) for g in groups if g]
    if not unwrapped:
        return unwrapped
    ref = sum(p[1] for p in unwrapped[0]) / len(unwrapped[0])
    aligned = [unwrapped[0]]
    for group in unwrapped[1:]:
        mean = sum(p[1] for p in group) / len(group)
        shift = 360.0 * round((ref - mean) / 360.0)
        aligned.append([(lat, lon + shift) for lat, lon in group])
    return aligned


def lon_shift_into(lon: float, lo: float, hi: float) -> float | None:
    """Return ``lon`` shifted by a multiple of 360° to lie in ``[lo, hi]``.

    Used to place labels for [-180, 180] data on a map whose extent was
    unwrapped past ±180. Returns None when no shift lands inside the range.
    """
    for shift in (0.0, -360.0, 360.0):
        if lo <= lon + shift <= hi:
            return lon + shift
    return None


def bounds_visible(bounds, extent) -> bool:
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


def normalize_polygon_order(coords):
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
        if not polygon_self_intersects(ring):
            return coords
        reordered = order_by_centroid_angle(ring)
        if polygon_self_intersects(reordered):
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


def polygon_groups(coords):
    """Return ``coords`` as a list of polygon groups, or None if not a polygon.

    A multi-area NOTAM (list of lists) gives one group per area; a single
    polygon (list of ``(lat, lon)``) is treated as a list of one. Longitudes
    are unwrapped first so a polygon crossing the 180° meridian is one
    continuous ring (e.g. 165..215 instead of jumping 179 -> -175); the
    wrap-around edges would otherwise look like self-intersections, blow the
    extent up to the whole globe, and draw the area the long way round. Then
    vertices listed out of geometric order (a "bowtie") are untangled.
    """
    if is_multi_polygon(coords):
        groups = coords
    elif isinstance(coords, list) and coords:
        groups = [coords]
    else:
        return None
    return [normalize_polygon_order(g) for g in unwrap_groups(groups)]


def parse_radius(radius_nm) -> float | None:
    """Return ``radius_nm`` as a positive float, or None."""
    try:
        if radius_nm is None:
            return None
        value = float(str(radius_nm).strip())
    except Exception:
        return None
    return value if value > 0 else None
