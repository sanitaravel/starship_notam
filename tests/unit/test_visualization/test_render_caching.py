"""Map data and fonts are loaded once per process, not on every render.

Regression test for fix-plan step 12: every render re-read the country and
water shapefiles, tried to download three non-existent geographic-name
layers, and re-resolved every font.
"""

from __future__ import annotations

import pytest

from starship_notam.visualization import image_composer, map_renderer


@pytest.fixture(autouse=True)
def clear_caches():
    map_renderer._natural_earth_records.cache_clear()
    yield
    map_renderer._natural_earth_records.cache_clear()


def test_missing_layer_is_attempted_only_once(monkeypatch):
    from cartopy.io import shapereader

    calls = []

    def missing(**kwargs):
        calls.append(kwargs)
        raise OSError("download failed")

    monkeypatch.setattr(shapereader, "natural_earth", missing)

    assert map_renderer._natural_earth_records("10m", "cultural", "nope") == ()
    assert map_renderer._natural_earth_records("10m", "cultural", "nope") == ()
    assert len(calls) == 1


def test_layer_records_are_reused(monkeypatch):
    from cartopy.io import shapereader

    calls = []
    monkeypatch.setattr(
        shapereader, "natural_earth", lambda **kw: calls.append(kw) or "layer.shp"
    )

    class FakeRecord:
        attributes = {"NAME": "Somewhere"}
        geometry = object()

    class FakeReader:
        def __init__(self, path):
            assert path == "layer.shp"

        def records(self):
            return [FakeRecord()]

    monkeypatch.setattr(shapereader, "Reader", FakeReader)

    first = map_renderer._natural_earth_records("50m", "cultural", "admin_0_countries")
    second = map_renderer._natural_earth_records("50m", "cultural", "admin_0_countries")

    assert first is second
    assert first[0][0] == {"NAME": "Somewhere"}
    assert len(calls) == 1


def test_fonts_are_cached():
    assert image_composer.load_font("JetBrainsMono-Bold.ttf", 48) is image_composer.load_font(
        "JetBrainsMono-Bold.ttf", 48
    )
    assert map_renderer._label_font(9) is map_renderer._label_font(9)
