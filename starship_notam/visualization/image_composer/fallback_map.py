"""Plain PIL map, drawn in place of the Cartopy map when that rendering fails."""

from __future__ import annotations

import math

from starship_notam.core.logging import logger
from starship_notam.visualization.image_composer.layout import BG_COLOR
from starship_notam.visualization.map_renderer import MAP_H, MAP_W
from starship_notam.visualization.map_renderer.geometry import unwrap_groups


def draw_fallback_map(img, map_x: int, map_y: int, coords, radius_nm):
    """Draw the NOTAM area on a blank map box at ``(map_x, map_y)``.

    Polygons are scaled to fill the box; a point with a radius becomes an
    ellipse; a point without one is not drawn (no marker, by request). Returns
    the image, which is a new object when an area was composited onto it.
    """
    from PIL import Image, ImageDraw

    draw = ImageDraw.Draw(img)
    map_box = (map_x, map_y, map_x + MAP_W, map_y + MAP_H)
    # Fallback: draw plain map background (match canvas background to avoid seams)
    draw.rectangle(map_box, fill=BG_COLOR)
    try:
        if isinstance(coords, list) and coords:
            # Normalize to a list of polygon groups so a multi-area NOTAM
            # (list-of-lists) and a single polygon (flat list of points)
            # share one drawing path. Each group is drawn separately.
            # Unwrap longitudes so an area crossing the 180° meridian is
            # drawn in one piece rather than stretched across the map.
            if isinstance(coords[0], list):
                groups = unwrap_groups(coords)
            else:
                groups = unwrap_groups([coords])
            all_pts = [pt for g in groups for pt in g]
            lats = [p[0] for p in all_pts]
            lons = [p[1] for p in all_pts]
            min_lat, max_lat = min(lats), max(lats)
            min_lon, max_lon = min(lons), max(lons)
            pad = 16
            avail_w = MAP_W - pad * 2
            avail_h = MAP_H - pad * 2
            lat_span = max_lat - min_lat or 1e-6
            lon_span = max_lon - min_lon or 1e-6
            scale = min(avail_w / lon_span, avail_h / lat_span)
            center_lat = (max_lat + min_lat) / 2.0
            center_lon = (max_lon + min_lon) / 2.0
            overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
            od = ImageDraw.Draw(overlay)
            for group in groups:
                pts = []
                for lat, lon in group:
                    x = int(map_x + pad + avail_w / 2.0 + (lon - center_lon) * scale)
                    y = int(map_y + pad + avail_h / 2.0 - (lat - center_lat) * scale)
                    pts.append((x, y))
                if len(pts) >= 2:
                    od.polygon(pts, fill=(207, 0, 0, 80), outline=(255, 80, 80, 200))
            img = Image.alpha_composite(img, overlay)
        elif isinstance(coords, tuple) and coords:
            lat, lon = coords
            r = None
            try:
                if radius_nm is not None:
                    r = float(str(radius_nm).strip())
                    if r <= 0:
                        r = None
            except Exception:
                r = None
            if r is not None:
                # Render a simple circle in fallback mode around center.
                lat_span = max((r / 60.0) * 4.0, 0.3)
                lon_span = max((r / (60.0 * max(math.cos(math.radians(lat)), 1e-6))) * 4.0, 0.3)
                min_lat, max_lat = lat - lat_span / 2.0, lat + lat_span / 2.0
                min_lon, max_lon = lon - lon_span / 2.0, lon + lon_span / 2.0
                pad = 16
                avail_w = MAP_W - pad * 2
                avail_h = MAP_H - pad * 2
                scale = min(avail_w / max(max_lon - min_lon, 1e-6), avail_h / max(max_lat - min_lat, 1e-6))
                cx = int(map_x + pad + avail_w / 2.0)
                cy = int(map_y + pad + avail_h / 2.0)
                rx = max(1, int((r / (60.0 * max(math.cos(math.radians(lat)), 1e-6))) * scale))
                ry = max(1, int((r / 60.0) * scale))
                overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
                od = ImageDraw.Draw(overlay)
                od.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=(207, 0, 0, 80), outline=(255, 80, 80, 200), width=2)
                img = Image.alpha_composite(img, overlay)
        # If coords is a single tuple and no radius is available, don't draw marker per request
    except Exception:
        logger.exception("Fallback drawing failed")
    return img
