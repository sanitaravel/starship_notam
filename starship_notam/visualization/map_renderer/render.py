"""Render the map tile: set up the figure, draw every layer, return a PIL image."""

from __future__ import annotations

import io

from PIL import Image

from starship_notam.core.logging import logger
from starship_notam.visualization.map_renderer.extent import fit_extent
from starship_notam.visualization.map_renderer.geometry import parse_radius, polygon_groups
from starship_notam.visualization.map_renderer.graticule import draw_graticule
from starship_notam.visualization.map_renderer.labels import draw_labels
from starship_notam.visualization.map_renderer.layers import add_base_layers, draw_geometry

# Right map fixed size (pixels). Kept here so callers may reference them.
MAP_W = 743
MAP_H = 662


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

    groups = polygon_groups(coords)
    point = coords if isinstance(coords, tuple) and coords else None
    radius_value = parse_radius(radius_nm)
    points = [pt for g in groups for pt in g] if groups else None
    extent = fit_extent(points, point, radius_value, size)

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

    add_base_layers(ax, cfeature)
    draw_graticule(ax, proj, extent, central_lon)
    draw_labels(ax, proj, extent, size, central_lon)
    draw_geometry(ax, proj, groups, point, radius_value, central_lon)

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
