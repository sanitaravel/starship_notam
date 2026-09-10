"""Unit tests for :mod:`starship_notam.parsers.notam_parser`.

Covers ``parse_notam`` (labelled ICAO fields + CARF autodetect) and
``parse_carf_message`` with known inputs, plus a determinism check
(Requirement 3.6): identical input yields identical output.

These tests import only the parsers layer — no database, Selenium, or
Telegram side effects (Requirements 9.1, 9.4).
"""

from __future__ import annotations

from starship_notam.parsers import parse_carf_message, parse_notam


# ---------------------------------------------------------------------------
# parse_notam — labelled ICAO fields
# ---------------------------------------------------------------------------
def test_parse_notam_extracts_labelled_fields(sample_notam_text):
    result = parse_notam(sample_notam_text)

    assert result["A"] == "KZHU"
    assert result["F"] == "SFC"
    assert result["G"] == "18000FT"
    assert result["E"].startswith("STARSHIP SUPER HEAVY LAUNCH OPERATIONS.")


def test_parse_notam_normalizes_b_and_c_to_iso(sample_notam_text):
    result = parse_notam(sample_notam_text)

    # B) 2607081350 and C) 2607160500 are parsed as YYMMDDhhmm.
    assert result["B"] == "2026-07-08T13:50:00Z"
    assert result["C"] == "2026-07-16T05:00:00Z"


def test_parse_notam_parses_q_line_into_subfields(sample_notam_text):
    result = parse_notam(sample_notam_text)
    q = result["Q"]

    assert isinstance(q, dict)
    assert q["location"] == "KZHU"
    assert q["q_code"] == "QRTCA"
    assert q["traffic"] == "IV"
    assert q["traffic_rule"] == "BO"
    assert q["lower"] == "000"
    assert q["upper"] == "180"
    assert q["coordinates"] == "2559N09709W"
    assert q["radius_nm"] == "025"


def test_parse_notam_without_labels_falls_back_to_e():
    result = parse_notam("SOME UNLABELLED FREE TEXT WITH NO FIELDS")

    assert result["E"] == "SOME UNLABELLED FREE TEXT WITH NO FIELDS"


def test_parse_notam_autodetects_carf_message(sample_carf_text):
    # A message beginning with "!CARF" is routed to parse_carf_message,
    # so parse_notam and parse_carf_message must agree.
    assert parse_notam(sample_carf_text) == parse_carf_message(sample_carf_text)


# ---------------------------------------------------------------------------
# parse_carf_message
# ---------------------------------------------------------------------------
def test_parse_carf_message_header_fields(sample_carf_text):
    result = parse_carf_message(sample_carf_text)

    assert result["source"] == "CARF"
    assert result["notam_id"] == "06/123"
    assert result["artcc"] == "ZHU"
    assert result["operation"] == "STARSHIP LAUNCH OPERATIONS AREA"


def test_parse_carf_message_altitude_block(sample_carf_text):
    result = parse_carf_message(sample_carf_text)

    assert result["altitude"] == "SFC-18000FT"
    assert result["altitude_min"] == "SFC"
    assert result["altitude_max"] == "18000 FT"


def test_parse_carf_message_polygon(sample_carf_text):
    result = parse_carf_message(sample_carf_text)
    polygon = result["polygon"]

    assert [p["raw"] for p in polygon] == [
        "255950N0970921W",
        "260500N0970500W",
        "255400N0964800W",
    ]
    # First vertex decoded to decimal degrees (25°59'50"N, 097°09'21"W).
    first = polygon[0]
    assert abs(first["lat"] - 25.99722) < 1e-4
    assert abs(first["lon"] - (-97.15583)) < 1e-4


def test_parse_carf_message_validity_window(sample_carf_text):
    result = parse_carf_message(sample_carf_text)

    assert result["validity_start"] == "2026-07-08T13:50:00Z"
    assert result["validity_end"] == "2026-07-16T05:00:00Z"
    # Aliases mirror the validity window.
    assert result["B"] == result["validity_start"]
    assert result["C"] == result["validity_end"]


def test_parse_carf_message_q_coordinates_populated(sample_carf_text):
    result = parse_carf_message(sample_carf_text)
    q = result["Q"]

    assert q["coordinates"] == (
        "255950N0970921W TO 260500N0970500W TO 255400N0964800W"
    )
    assert q["lower"] == "SFC"
    assert q["upper"] == "18000 FT"


# ---------------------------------------------------------------------------
# Determinism (Requirement 3.6)
# ---------------------------------------------------------------------------
def test_parse_notam_is_deterministic(sample_notam_text):
    assert parse_notam(sample_notam_text) == parse_notam(sample_notam_text)


def test_parse_carf_message_is_deterministic(sample_carf_text):
    assert parse_carf_message(sample_carf_text) == parse_carf_message(
        sample_carf_text
    )
