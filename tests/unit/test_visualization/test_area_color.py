"""Area colour: NOTAM areas are drawn red, maritime (BNM) areas blue."""

from __future__ import annotations

from src.visualization.image_composer import render
from src.visualization.image_composer.card_data import bnm_card_data, notam_from_db_row
from src.visualization.map_renderer import AREA_BLUE, AREA_RED
from src.visualization.map_renderer.layers import draw_geometry

_SQUARE = [(26.0, -97.0), (26.0, -96.0), (25.0, -96.0), (25.0, -97.0)]


class _FakeAx:
    def __init__(self):
        self.styles = []

    def add_geometries(self, geoms, crs, **style):
        self.styles.append(style)


def test_bnm_card_asks_for_blue_area():
    card = bnm_card_data({"bnm_id": "CGD-H BNM 0108-26", "areas": [{"coords": _SQUARE}]})
    assert card["area_color"] == AREA_BLUE


def test_notam_card_keeps_default_red_area():
    card = notam_from_db_row("1/2345", {"E": "TEMPORARY FLIGHT RESTRICTION"})
    assert card.get("area_color") in (None, AREA_RED)


def test_draw_geometry_uses_requested_color():
    ax = _FakeAx()
    draw_geometry(ax, None, [_SQUARE], None, None, 0.0, AREA_BLUE)
    draw_geometry(ax, None, None, (26.0, -97.0), 5.0, 0.0)
    blue, red = ax.styles
    assert blue["edgecolor"][:3] == tuple(c / 255 for c in AREA_BLUE)
    assert red["edgecolor"][:3] == tuple(c / 255 for c in AREA_RED)


def test_card_passes_area_color_to_map(monkeypatch, tmp_path):
    seen = {}

    def fake_render_map(coords, size, radius_nm=None, area_color=AREA_RED):
        seen["area_color"] = area_color
        raise RuntimeError("stop after capturing the colour")

    monkeypatch.setattr(render, "render_map", fake_render_map)
    card = bnm_card_data({"bnm_id": "CGD-H BNM 0108-26", "areas": [{"coords": _SQUARE}]})
    try:
        render.render_notam_image(card, output_path=str(tmp_path / "card.png"))
    except Exception:
        pass
    assert seen["area_color"] == AREA_BLUE
