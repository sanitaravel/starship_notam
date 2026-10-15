"""PIL-based NOTAM image composition.

This package composes the final NOTAM image: it lays out the canvas, loads the
project fonts, renders the descriptive text (title, number, details, times,
zone/height), and pastes the map tile produced by
:func:`src.visualization.map_renderer.render_map`.

Coordinate extraction is delegated to
:func:`src.parsers.coord_parser.parse_coords_from_text` (the
visualization layer contains no coordinate-parsing logic of its own).

Heavy image dependencies (Pillow) are imported lazily inside the function
bodies so that importing this package does not require Pillow to be installed
and keeps the visualization layer independently importable.

Submodules:
    render        render_notam_image, plot_single_notam
    card_data     stored NOTAM row -> the dict the card is drawn from
    titles        short Russian title lines for Starship NOTAMs
    fallback_map  plain PIL map drawn when Cartopy rendering fails
    layout        canvas size, padding and colours

Public entry points:
    render_notam_image(notam_dict, output_path) -> str
    plot_single_notam(name, parsed, out_path) -> str
"""

from src.visualization.image_composer.render import (
    plot_single_notam,
    render_notam_image,
)
from src.visualization.image_composer.titles import extract_starship_template

__all__ = [
    "extract_starship_template",
    "plot_single_notam",
    "render_notam_image",
]
