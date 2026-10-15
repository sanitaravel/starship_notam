"""Fonts for the NOTAM card (Pillow) and the map labels (Matplotlib).

Both prefer the JetBrains Mono files bundled in the project's ``fonts/``
directory. Pillow and Matplotlib are imported lazily inside the loaders.
"""

from __future__ import annotations

import functools
from pathlib import Path

from starship_notam.core.logging import logger

# Fonts directory lives at the project root, two levels up from this file:
#   starship_notam/visualization/fonts.py -> starship_notam/ -> project root
FONTS_DIR = Path(__file__).resolve().parents[2] / "fonts"


@functools.lru_cache(maxsize=None)
def load_font(name: str, size: int, weight: str | None = None):
    """Load a TrueType font, preferring the project's ``fonts/`` directory.

    Falls back to common system font locations and finally to PIL's default
    font if nothing suitable can be loaded. Cached: each image needs seven
    fonts, and the lookup searches the fonts folder every time.
    """
    from PIL import ImageFont

    project_fonts = FONTS_DIR
    candidates = []

    # Exact file in project fonts
    if project_fonts.exists():
        exact = project_fonts / name
        candidates.append(str(exact))
        # Look for files that mention JetBrains or the base name
        for f in project_fonts.glob("*.ttf"):
            fn = f.name.lower()
            if name.lower() in fn or "jetbrains" in fn:
                candidates.append(str(f))

    # System font locations
    import os

    candidates.extend([
        os.path.join("/usr/share/fonts", name),
        os.path.join("/Library/Fonts", name),
        os.path.join(str(Path.home()), ".fonts", name),
        name,
    ])

    seen = set()
    for c in candidates:
        if not c or c in seen:
            continue
        seen.add(c)
        try:
            logger.debug("Trying font candidate: %s", c)
            return ImageFont.truetype(c, size)
        except Exception:
            continue

    logger.warning("Falling back to default PIL font for size %s", size)
    return ImageFont.load_default()


@functools.lru_cache(maxsize=None)
def jetbrains_font_path() -> str | None:
    """Path of the bundled JetBrains Mono font, or None if it is missing."""
    if FONTS_DIR.exists():
        for f in sorted(FONTS_DIR.glob("*.ttf")):
            if "jetbrains" in f.name.lower():
                return str(f)
    return None


@functools.lru_cache(maxsize=None)
def label_font(size: float | None):
    """Cached FontProperties for map labels (JetBrains Mono, else monospace).

    Matplotlib copies the properties into each Text, so sharing is safe.
    """
    import matplotlib.font_manager as fm

    path = jetbrains_font_path()
    if path:
        return fm.FontProperties(fname=path, size=size)
    return fm.FontProperties(family="monospace", size=size)
