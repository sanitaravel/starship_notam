"""Natural Earth layers, loaded once per process."""

from __future__ import annotations

import functools

from starship_notam.core.logging import logger

# Cache of Natural Earth land geometries (prepared for fast intersection tests).
_LAND_GEOMS_CACHE = None


def land_geometries():
    """Return a list of Natural Earth land geometries, loaded lazily and cached.

    Returns an empty list if the Natural Earth data or shapely cannot be loaded,
    so callers can degrade gracefully (treat as "no land information available").
    """
    global _LAND_GEOMS_CACHE
    if _LAND_GEOMS_CACHE is not None:
        return _LAND_GEOMS_CACHE
    geoms: list = []
    try:
        from cartopy.io import shapereader

        land_shp = shapereader.natural_earth(
            resolution="50m", category="physical", name="land"
        )
        reader = shapereader.Reader(land_shp)
        geoms = [rec.geometry for rec in reader.records() if rec.geometry is not None]
    except Exception:
        logger.exception("Could not load Natural Earth land geometries for land-visibility check")
        geoms = []
    _LAND_GEOMS_CACHE = geoms
    return geoms


@functools.lru_cache(maxsize=None)
def natural_earth_records(resolution: str, category: str, name: str) -> tuple:
    """Return ``(attributes, geometry)`` pairs for a Natural Earth layer.

    Loaded once per process and cached; reading the shapefiles on every render
    was a large part of render time. A layer that cannot be loaded yields an
    empty tuple, which is cached too, so it is not re-downloaded each render.
    """
    try:
        from cartopy.io import shapereader

        path = shapereader.natural_earth(resolution=resolution, category=category, name=name)
        return tuple(
            (rec.attributes, rec.geometry)
            for rec in shapereader.Reader(path).records()
            if rec.geometry is not None
        )
    except Exception:
        logger.exception("Could not load Natural Earth layer %s/%s/%s", resolution, category, name)
        return ()
