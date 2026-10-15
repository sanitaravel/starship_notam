"""Place-name labels: countries, oceans and lakes, and the Starbase marker."""

from __future__ import annotations

from src.core.logging import logger
from src.visualization.fonts import label_font
from src.visualization.map_renderer.geometry import bounds_visible, lon_shift_into
from src.visualization.map_renderer.natural_earth import natural_earth_records

# Place-name labels: lighter than the ocean (#262626 -> #858585).
_LABEL_COLOR = "#858585"
STARBASE_LAT = 25.9896
STARBASE_LON = -97.1849


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
            if not bounds_visible((minx, miny, maxx, maxy), extent):
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
            lx = lon_shift_into(label_pt.x, ext_min_lon + lon_margin, ext_max_lon - lon_margin)
            ly = label_pt.y
            # ensure label point is comfortably inside the visible extent
            if lx is None or not (ext_min_lat + lat_margin <= ly <= ext_max_lat - lat_margin):
                continue
            txt = ax.text(lx - central_lon, ly, name, fontproperties=label_font(font_size(maxpix)), color=_LABEL_COLOR, transform=proj, ha='center', va='center', zorder=zorder, clip_on=True, **extra)
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
    star_lon = lon_shift_into(STARBASE_LON, ext_min_lon, ext_max_lon)
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
        stxt = ax.text(x + dx, STARBASE_LAT + dy, 'Starbase, TX', fontproperties=label_font(sfontsize), color=_LABEL_COLOR, transform=proj, ha='left', va='bottom', zorder=13, clip_on=True)
        stxt.set_path_effects([patheffects.withStroke(linewidth=1.8, foreground='black')])
        try:
            stxt.set_clip_path(ax.patch)
        except Exception:
            pass
    except Exception:
        pass


def draw_labels(ax, proj, extent, size, central_lon) -> None:
    """Label visible countries and large water bodies, and mark Starbase."""
    try:
        # Countries from Natural Earth admin_0_countries.
        _label_layer(
            ax, proj, extent, size, central_lon,
            natural_earth_records('50m', 'cultural', 'admin_0_countries'),
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
                natural_earth_records('50m', 'physical', layer),
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
