"""Latitude/longitude grid lines with labels drawn inside the map."""

from __future__ import annotations

import math

from src.core.logging import logger
from src.visualization.fonts import jetbrains_font_path, label_font


def nice_grid_step(span: float) -> float:
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


def frange(start: float, stop: float, step: float) -> list[float]:
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


def format_degrees(value: float) -> str:
    """Format an absolute degree magnitude, trimming trailing zeros.

    Examples: 120.0 -> "120", 0.5 -> "0.5", 29.25 -> "29.25".
    """
    mag = abs(value)
    if abs(mag - round(mag)) < 1e-6:
        return f"{int(round(mag))}"
    # Up to two decimals, then strip trailing zeros and a dangling dot.
    return f"{mag:.2f}".rstrip('0').rstrip('.')


def format_lon(lon: float) -> str:
    """Format a longitude as e.g. ``120°W`` / ``75°E`` / ``0°``.

    Longitudes are normalized to the [-180, 180] range before formatting so
    zoomed-out views that wrap past +/-180 still show sensible values.
    """
    norm = ((lon + 180.0) % 360.0) - 180.0
    if abs(norm) < 1e-6 or abs(abs(norm) - 180.0) < 1e-6:
        return f"{format_degrees(norm)}°"
    hemi = 'E' if norm > 0 else 'W'
    return f"{format_degrees(norm)}°{hemi}"


def format_lat(lat: float) -> str:
    """Format a latitude as e.g. ``29°S`` / ``5°N`` / ``0°``."""
    if abs(lat) < 1e-6:
        return "0°"
    hemi = 'N' if lat > 0 else 'S'
    return f"{format_degrees(lat)}°{hemi}"


def draw_graticule(ax, proj, extent, central_lon: float) -> None:
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
        lon_step = nice_grid_step(lon_span)
        lat_step = nice_grid_step(lat_span)

        # Compute tick positions covering the visible extent, snapped to
        # multiples of the chosen step.
        lon_start = math.floor(extent[0] / lon_step) * lon_step
        lon_end = math.ceil(extent[1] / lon_step) * lon_step
        lat_start = math.floor(extent[2] / lat_step) * lat_step
        lat_end = math.ceil(extent[3] / lat_step) * lat_step
        lon_ticks = frange(lon_start, lon_end, lon_step)
        lat_ticks = [t for t in frange(lat_start, lat_end, lat_step) if -90.0 <= t <= 90.0]

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
        if jetbrains_font_path() is not None:
            text_kwargs['fontproperties'] = label_font(None)

        # Longitude labels: one per vertical line, along the bottom edge.
        for lon_v in lon_ticks:
            if extent[0] <= lon_v <= extent[1]:
                ax.text(
                    lon_v - central_lon, lat_inset, format_lon(lon_v),
                    ha='center', va='bottom', **text_kwargs,
                )
        # Latitude labels: one per horizontal line, along the left edge.
        for lat_v in lat_ticks:
            if extent[2] <= lat_v <= extent[3]:
                ax.text(
                    lon_inset - central_lon, lat_v, format_lat(lat_v),
                    ha='left', va='center', **text_kwargs,
                )
    except Exception:
        logger.exception("Failed to draw coordinate gridlines")
