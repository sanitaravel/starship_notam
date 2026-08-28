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

import io
from pathlib import Path

from PIL import Image

from starship_notam.core.logging import logger

# Right map fixed size (pixels). Kept here so callers may reference them.
MAP_W = 743
MAP_H = 662

# Map extent scale: values >1 slightly zoom out (makes NOTAM area appear smaller)
MAP_EXTENT_SCALE = 2

# Fonts directory lives at the project root, two levels up from this file:
#   starship_notam/visualization/map_renderer.py -> starship_notam/ -> project root
_FONTS_DIR = Path(__file__).resolve().parents[2] / "fonts"


def render_map(coords, size: tuple[int, int] = (MAP_W, MAP_H), radius_nm: float | None = None) -> "Image.Image":
    """Render a map image (PIL.Image) showing the given coords polygon or point using Cartopy.

    Returns an RGBA PIL Image of exact ``size``.

    Parameters
    ----------
    coords :
        Either a list of ``(lat, lon)`` tuples describing a polygon, a single
        ``(lat, lon)`` tuple describing a point, or ``None``/empty for a default
        global extent.
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
        from shapely.geometry import Polygon, Point
    except Exception as e:
        logger.exception("Cartopy/Matplotlib not available: %s", e)
        raise ImportError(
            "cartopy and matplotlib are required for map rendering; "
            "install them via requirements.txt"
        ) from e

    fig_dpi = 100
    fig_w = size[0] / fig_dpi
    fig_h = size[1] / fig_dpi
    logger.info("Creating map figure with size %dx%d pixels (%.2fx%.2f inches at %d DPI)", size[0], size[1], fig_w, fig_h, fig_dpi)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=fig_dpi, subplot_kw=dict(projection=ccrs.PlateCarree()))
    # fill background
    # Match figure and axes background to the canvas ocean color (#262626)
    fig.patch.set_facecolor('#262626')
    ax.set_facecolor('#262626')
    # Some GeoAxes implementations may not have outline_patch; guard access
    try:
        if hasattr(ax, 'outline_patch') and ax.outline_patch is not None:
            ax.outline_patch.set_visible(False)
    except Exception:
        logger.exception("Failed to hide axes outline, map may have unexpected border")
        pass

    # compute extent
    radius_value = None
    try:
        if radius_nm is not None:
            radius_value = float(str(radius_nm).strip())
            if radius_value <= 0:
                radius_value = None
    except Exception:
        radius_value = None

    if isinstance(coords, list) and coords:
        logger.info("Rendering polygon with %d points on map", len(coords))
        import math
        lats = [p[0] for p in coords]
        lons = [p[1] for p in coords]
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
        # Apply global extent scale so the mapped area is slightly larger (zoom out).
        try:
            center_lon = (extent[0] + extent[1]) / 2.0
            center_lat = (extent[2] + extent[3]) / 2.0
            half_lon = (extent[1] - extent[0]) / 2.0
            half_lat = (extent[3] - extent[2]) / 2.0
            half_lon *= MAP_EXTENT_SCALE
            half_lat *= MAP_EXTENT_SCALE
            extent = [center_lon - half_lon, center_lon + half_lon, center_lat - half_lat, center_lat + half_lat]
        except Exception:
            pass
    elif isinstance(coords, tuple) and coords:
        logger.info("Rendering single point on map at lat=%.4f, lon=%.4f", coords[0], coords[1])
        import math
        lat, lon = coords
        if radius_value is not None:
            base_half_lat = max(radius_value / 60.0, 0.15)
            cos_lat = max(math.cos(math.radians(lat)), 1e-6)
            base_half_lon = max(radius_value / (60.0 * cos_lat), 0.15)
        else:
            # base half-spans (degrees)
            base_half_lat = 1.0
            base_half_lon = 1.0
        map_w, map_h = size
        desired_ratio = float(map_w) / float(map_h)
        center_lat = lat
        cos_lat = max(math.cos(math.radians(center_lat)), 1e-6)
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
        # Scale halves slightly so the point area appears smaller on the map (zoom out)
        try:
            half_lon *= MAP_EXTENT_SCALE
            half_lat *= MAP_EXTENT_SCALE
        except Exception:
            pass
        extent = [lon - half_lon, lon + half_lon, lat - half_lat, lat + half_lat]
    else:
        logger.info("No valid coordinates provided, using default global extent")
        extent = [-180, 180, -90, 90]

    ax.set_extent(extent, crs=ccrs.PlateCarree())

    # Add simple cartographic features with dark theme
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

    # Label visible countries and large named geographic features (islands, peninsulas)
    try:
        # imports localized so failure here doesn't break map drawing
        from cartopy.io import shapereader
        import matplotlib.patheffects as patheffects
        import matplotlib.font_manager as fm
        # choose a label color lighter than the ocean (#262626 -> #858585)
        label_color = "#858585"
        # prefer JetBrains Mono bundled in project's fonts/ directory when available
        jet_font_path = None
        project_fonts = _FONTS_DIR
        if project_fonts.exists():
            for f in project_fonts.glob("*.ttf"):
                fn = f.name.lower()
                if 'jetbrains' in fn or 'jetbrainsmono' in fn or 'jetbrains-mono' in fn:
                    jet_font_path = str(f)
                    break

        # Precompute extent and margins used by multiple labelers
        ext_min_lon, ext_max_lon, ext_min_lat, ext_max_lat = extent[0], extent[1], extent[2], extent[3]
        ext_lon_span = max(ext_max_lon - ext_min_lon, 1e-6)
        ext_lat_span = max(ext_max_lat - ext_min_lat, 1e-6)
        margin_factor = 0.03
        lon_margin = ext_lon_span * margin_factor
        lat_margin = ext_lat_span * margin_factor

        # Helper: label countries from Natural Earth admin_0_countries
        try:
            countries_shp = shapereader.natural_earth(resolution='50m', category='cultural', name='admin_0_countries')
            reader = shapereader.Reader(countries_shp)
            # extent = [min_lon, max_lon, min_lat, max_lat]
            ext_min_lon, ext_max_lon, ext_min_lat, ext_max_lat = extent[0], extent[1], extent[2], extent[3]
            ext_lon_span = max(ext_max_lon - ext_min_lon, 1e-6)
            ext_lat_span = max(ext_max_lat - ext_min_lat, 1e-6)
            # small margin so labels don't sit right on the border
            margin_factor = 0.03
            lon_margin = ext_lon_span * margin_factor
            lat_margin = ext_lat_span * margin_factor
            for rec in reader.records():
                try:
                    attrs = rec.attributes
                    name = attrs.get('ADMIN') or attrs.get('NAME') or attrs.get('NAME_LONG') or attrs.get('SOVEREIGNT')
                    if not name:
                        continue
                    geom = rec.geometry
                    if geom is None:
                        continue
                    minx, miny, maxx, maxy = geom.bounds
                    # quick intersection test against current extent
                    if maxx < ext_min_lon or minx > ext_max_lon or maxy < ext_min_lat or miny > ext_max_lat:
                        continue
                    # approximate pixel span of this feature within current extent
                    pixel_w = (maxx - minx) / ext_lon_span * size[0]
                    pixel_h = (maxy - miny) / ext_lat_span * size[1]
                    maxpix = max(pixel_w, pixel_h)
                    # skip small countries to avoid clutter; threshold tuned for readability
                    if maxpix < 60:
                        continue
                    # choose a point guaranteed to lie within the geometry for label placement
                    try:
                        label_pt = geom.representative_point()
                    except Exception:
                        label_pt = geom.centroid
                    lx, ly = label_pt.x, label_pt.y
                    # ensure label point is comfortably inside the visible extent
                    if not (ext_min_lon + lon_margin <= lx <= ext_max_lon - lon_margin and ext_min_lat + lat_margin <= ly <= ext_max_lat - lat_margin):
                        continue
                    # slightly reduce label size for readability and compactness
                    fontsize = max(7, min(12, int(maxpix / 18)))
                    if jet_font_path:
                        font_prop = fm.FontProperties(fname=jet_font_path, size=fontsize)
                    else:
                        font_prop = fm.FontProperties(family='monospace', size=fontsize)
                    txt = ax.text(lx, ly, name, fontproperties=font_prop, fontweight='bold', color=label_color, transform=ccrs.PlateCarree(), ha='center', va='center', zorder=11, clip_on=True)
                    txt.set_path_effects([patheffects.withStroke(linewidth=2, foreground='black')])
                    try:
                        txt.set_clip_path(ax.patch)
                    except Exception:
                        pass
                except Exception:
                    # continue labeling other features even if one fails
                    continue
        except Exception:
            logger.exception("Failed to load admin_0_countries shapefile for labeling")

        # Label visible large water bodies (oceans, named lakes) using physical layers
        try:
            water_candidates = [
                ('ocean', 'physical', '50m'),
                ('lakes', 'physical', '50m'),
                ('ocean', 'physical', '10m'),
                ('lakes', 'physical', '10m'),
            ]
            for name, category, res in water_candidates:
                try:
                    path = shapereader.natural_earth(resolution=res, category=category, name=name)
                    wreader = shapereader.Reader(path)
                except Exception:
                    wreader = None
                if not wreader:
                    continue
                for wrec in wreader.records():
                    try:
                        wattr = wrec.attributes
                        # common name keys
                        wname = (wattr.get('name') or wattr.get('NAME') or wattr.get('NAME_EN') or wattr.get('NAME_LONG') or wattr.get('NAME_HI') or '')
                        if not wname:
                            continue
                        wgeom = wrec.geometry
                        if wgeom is None:
                            continue
                        minx, miny, maxx, maxy = wgeom.bounds
                        # quick intersection test
                        if maxx < ext_min_lon or minx > ext_max_lon or maxy < ext_min_lat or miny > ext_max_lat:
                            continue
                        pixel_w = (maxx - minx) / ext_lon_span * size[0]
                        pixel_h = (maxy - miny) / ext_lat_span * size[1]
                        maxpix = max(pixel_w, pixel_h)
                        # only label sufficiently large water bodies
                        if maxpix < 60:
                            continue
                        try:
                            wlabel_pt = wgeom.representative_point()
                        except Exception:
                            wlabel_pt = wgeom.centroid
                        wx, wy = wlabel_pt.x, wlabel_pt.y
                        if not (ext_min_lon + lon_margin <= wx <= ext_max_lon - lon_margin and ext_min_lat + lat_margin <= wy <= ext_max_lat - lat_margin):
                            continue
                        # fontsize tuned to feature size
                        wfontsize = max(8, min(18, int(maxpix / 22)))
                        if jet_font_path:
                            wfont_prop = fm.FontProperties(fname=jet_font_path, size=wfontsize)
                        else:
                            wfont_prop = fm.FontProperties(family='monospace', size=wfontsize)
                        wtxt = ax.text(wx, wy, wname, fontproperties=wfont_prop, color=label_color, transform=ccrs.PlateCarree(), ha='center', va='center', zorder=10, clip_on=True)
                        wtxt.set_path_effects([patheffects.withStroke(linewidth=2, foreground='black')])
                        try:
                            wtxt.set_clip_path(ax.patch)
                        except Exception:
                            pass
                    except Exception:
                        continue
        except Exception:
            logger.debug("Water-body labeling failed or not available")

        # Try to label named geographic features (islands, peninsulas) from available geographic names
        try:
            geo_reader = None
            for candidate in ('geographic_names', 'ne_10m_geographic_names', '10m_geographic_names'):
                try:
                    path = shapereader.natural_earth(resolution='10m', category='cultural', name=candidate)
                    geo_reader = shapereader.Reader(path)
                    break
                except Exception:
                    geo_reader = None
            if geo_reader:
                # reuse label margins
                for rec in geo_reader.records():
                    try:
                        attrs = rec.attributes
                        fname = (attrs.get('NAME') or attrs.get('name') or attrs.get('NAME_EN') or attrs.get('NAME_LONG') or '')
                        featclass = (attrs.get('FEATURECLA') or attrs.get('featurecla') or '')
                        if not fname:
                            continue
                        lower_n = str(fname).lower()
                        lower_fc = str(featclass).lower()
                        if 'island' not in lower_n and 'island' not in lower_fc and 'isle' not in lower_n and 'peninsula' not in lower_n and 'peninsula' not in lower_fc:
                            continue
                        geom = rec.geometry
                        if geom is None:
                            continue
                        minx, miny, maxx, maxy = geom.bounds
                        if maxx < ext_min_lon or minx > ext_max_lon or maxy < ext_min_lat or miny > ext_max_lat:
                            continue
                        pixel_w = (maxx - minx) / ext_lon_span * size[0]
                        pixel_h = (maxy - miny) / ext_lat_span * size[1]
                        maxpix = max(pixel_w, pixel_h)
                        # allow slightly smaller threshold for named features
                        if maxpix < 30:
                            continue
                        try:
                            label_pt = geom.representative_point()
                        except Exception:
                            label_pt = geom.centroid
                        lx, ly = label_pt.x, label_pt.y
                        # ensure label point is inside visible area with margin
                        if not (ext_min_lon + lon_margin <= lx <= ext_max_lon - lon_margin and ext_min_lat + lat_margin <= ly <= ext_max_lat - lat_margin):
                            continue
                        # reduce feature label size slightly
                        fontsize = max(6, min(10, int(maxpix / 24)))
                        if jet_font_path:
                            font_prop = fm.FontProperties(fname=jet_font_path, size=fontsize)
                        else:
                            font_prop = fm.FontProperties(family='monospace', size=fontsize)
                        txt = ax.text(lx, ly, fname, fontproperties=font_prop, fontsize=fontsize, color=label_color, transform=ccrs.PlateCarree(), ha='center', va='center', zorder=11, clip_on=True)
                        txt.set_path_effects([patheffects.withStroke(linewidth=1.8, foreground='black')])
                        try:
                            txt.set_clip_path(ax.patch)
                        except Exception:
                            pass
                    except Exception:
                        continue
        except Exception:
            logger.debug("No geographic-names layer available or labeling failed")

        # Draw Starbase, TX marker and label if visible
        try:
            star_lat = 25.9896
            star_lon = -97.1849
            if ext_min_lon <= star_lon <= ext_max_lon and ext_min_lat <= star_lat <= ext_max_lat:
                # marker
                try:
                    ax.scatter([star_lon], [star_lat], s=70, color='#FF8014', edgecolors='black', linewidths=0.8, transform=ccrs.PlateCarree(), zorder=13)
                except Exception:
                    try:
                        ax.plot(star_lon, star_lat, marker='o', markersize=6, color='#FF8014', transform=ccrs.PlateCarree(), zorder=13)
                    except Exception:
                        pass
                # label offset a bit to the right and up
                try:
                    dx = ext_lon_span * 0.02
                    dy = ext_lat_span * 0.01
                    sname = 'Starbase, TX'
                    sfontsize = max(8, min(12, int(min(size) / 60)))
                    if jet_font_path:
                        sfont_prop = fm.FontProperties(fname=jet_font_path, size=sfontsize)
                    else:
                        sfont_prop = fm.FontProperties(family='monospace', size=sfontsize)
                    stxt = ax.text(star_lon + dx, star_lat + dy, sname, fontproperties=sfont_prop, color=label_color, transform=ccrs.PlateCarree(), ha='left', va='bottom', zorder=13, clip_on=True)
                    stxt.set_path_effects([patheffects.withStroke(linewidth=1.8, foreground='black')])
                    try:
                        stxt.set_clip_path(ax.patch)
                    except Exception:
                        pass
                except Exception:
                    pass
        except Exception:
            logger.debug('Starbase marker placement failed')

    except Exception:
        # drawing labels is non-critical; do not fail the whole rendering if shapereader/patheffects unavailable
        logger.debug("Shapereader or patheffects not available; skipping labels")
    # Draw polygon, circle, or point
    if isinstance(coords, list) and coords:
        poly_coords = [(lon, lat) for lat, lon in coords]
        try:
            poly = Polygon(poly_coords)
            logger.info("Drawing polygon on cartopy map")
            ax.add_geometries([poly], crs=ccrs.PlateCarree(), facecolor=(207/255, 0, 0, 0.18), edgecolor=(207/255, 0, 0, 0.95), linewidth=1.6)
        except Exception:
            logger.exception("Failed to draw polygon on cartopy map")
    elif isinstance(coords, tuple) and coords:
        lat, lon = coords
        if radius_value is not None:
            import math
            logger.info("Drawing circle on cartopy map with radius %.2f NM", radius_value)
            circle_pts = []
            lat_deg = radius_value / 60.0
            cos_lat = max(math.cos(math.radians(lat)), 1e-6)
            lon_deg = radius_value / (60.0 * cos_lat)
            for i in range(72):
                ang = 2.0 * math.pi * (i / 72.0)
                p_lat = lat + lat_deg * math.sin(ang)
                p_lon = lon + lon_deg * math.cos(ang)
                circle_pts.append((p_lon, p_lat))
            try:
                circle = Polygon(circle_pts)
                ax.add_geometries([circle], crs=ccrs.PlateCarree(), facecolor=(207/255, 0, 0, 0.18), edgecolor=(207/255, 0, 0, 0.95), linewidth=1.6)
            except Exception:
                logger.exception("Failed to draw circle geometry on cartopy map")
        else:
            logger.info("Drawing point on cartopy map")
            # Intentionally do not draw a center marker or coordinate label per request

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
