"""Multi-area NOTAMs must reach the renderer as separate polygon groups.

Regression test for fix-plan step 1: the orchestrator used to pass a flat
point list into ``plot_single_notam``, which overwrote the per-area groups
computed by ``_notam_from_db_row`` and fused two debris-response areas into
one self-intersecting ring.
"""

from __future__ import annotations

from starship_notam.visualization import image_composer

TWO_AREA_E = (
    "DRA BOUNDED BY: 1700N07140W-1626N07140W-1626N07300W-1700N07300W "
    "AND 1600N07029W-1548N06956W-1548N06813W-1600N06813W."
)


def _capture_rendered_notam(monkeypatch, name, parsed):
    captured = {}

    def fake_render(notam, output_path):
        captured["notam"] = notam
        return output_path

    monkeypatch.setattr(image_composer, "render_notam_image", fake_render)
    image_composer.plot_single_notam(name, parsed, "out.png")
    return captured["notam"]


def test_two_area_notam_is_rendered_as_two_groups(monkeypatch):
    notam = _capture_rendered_notam(monkeypatch, "A0001_26", {"E": TWO_AREA_E})

    coords = notam["coords"]
    assert isinstance(coords, list) and len(coords) == 2
    assert all(isinstance(group, list) and len(group) == 4 for group in coords)


def test_single_area_notam_stays_flat(monkeypatch):
    single = "AREA BOUNDED BY 1700N07140W-1626N07140W-1626N07300W-1700N07300W."
    notam = _capture_rendered_notam(monkeypatch, "A0002_26", {"E": single})

    coords = notam["coords"]
    assert len(coords) == 4
    assert all(isinstance(pt, tuple) for pt in coords)


def test_number_is_derived_from_stored_name(monkeypatch):
    notam = _capture_rendered_notam(monkeypatch, "A0669_26", {"E": TWO_AREA_E})

    assert notam["number"] == "A0669/26"
