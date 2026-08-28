"""Visualization package: map rendering and NOTAM image composition.

Re-exports the public visualization entry points:
    from starship_notam.visualization import render_map, render_notam_image

``render_map`` is available immediately. ``render_notam_image`` is provided via
a lazy PEP 562 ``__getattr__`` so this package remains importable before the
``image_composer`` module (task 5.2) exists, and so heavy dependencies are only
loaded on first access.
"""

from starship_notam.visualization.map_renderer import render_map

__all__ = [
    "render_map",
    "render_notam_image",
]


def __getattr__(name):
    """Lazily resolve ``render_notam_image`` from the image_composer module."""
    if name == "render_notam_image":
        from starship_notam.visualization.image_composer import render_notam_image

        return render_notam_image
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
