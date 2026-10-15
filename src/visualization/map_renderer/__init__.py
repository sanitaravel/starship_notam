"""Cartopy/Matplotlib map rendering for NOTAM visualization.

This package renders a map image (as a :class:`PIL.Image.Image`) showing a
NOTAM polygon, circle, or point using Cartopy and Matplotlib.

The heavy plotting dependencies (``matplotlib``, ``cartopy``, ``shapely``) are
imported lazily inside the functions that use them so that importing this
package does not require those packages to be installed. This keeps the
visualization layer independently importable in test environments.

If Cartopy/Matplotlib/Shapely are unavailable when :func:`render_map` is called,
an :class:`ImportError` with a clear message identifying the missing dependency
is raised.

Submodules:
    render         render_map: figure set-up, drawing order, PNG output
    geometry       polygon groups: antimeridian unwrapping, bowtie untangling
    extent         fitting the view to the NOTAM, zooming out to show land
    natural_earth  cached Natural Earth land and label layers
    layers         base map layers and the NOTAM area itself
    graticule      latitude/longitude lines and their labels
    labels         country, water body and Starbase labels
"""

from src.visualization.map_renderer.render import MAP_H, MAP_W, render_map

__all__ = [
    "MAP_H",
    "MAP_W",
    "render_map",
]
