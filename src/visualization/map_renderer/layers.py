"""Base map layers (dark theme) and the NOTAM area drawn on top of them."""

from __future__ import annotations

import math

from src.core.logging import logger

# Fill/outline used for every NOTAM area (polygon or circle).
_AREA_STYLE = dict(
    facecolor=(207 / 255, 0, 0, 0.18),
    edgecolor=(207 / 255, 0, 0, 0.95),
    linewidth=1.6,
)


def add_base_layers(ax, cfeature) -> None:
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


def draw_geometry(ax, proj, polygon_groups, point, radius_value, central_lon) -> None:
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
