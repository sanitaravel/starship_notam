"""Unit tests for :mod:`starship_notam.bot.formatting`.

These tests exercise the four public formatting functions with known input
dictionaries and assert on the produced HTML strings. They also verify
(Requirements 5.1 and 5.5) that the formatting module imports cleanly WITHOUT
the Telegram API (``python-telegram-bot`` / the ``telegram`` package) being
required or pulled in as a side effect of the import.

The formatting layer performs no network or database I/O, so no mocking or
fixtures beyond the plain input dicts are needed.
"""

from __future__ import annotations

import sys

import pytest

from starship_notam.bot import formatting


# ---------------------------------------------------------------------------
# Requirement 5.1 / 5.5 — module imports without the Telegram API
# ---------------------------------------------------------------------------
def test_formatting_imports_without_telegram_api():
    """Importing the formatting module must succeed on its own.

    A fresh import of ``starship_notam.bot.formatting`` must not fail and must
    expose the public formatting functions. This guards Requirement 5.1: the
    formatting module does not import the Telegram API.
    """
    import importlib

    module = importlib.import_module("starship_notam.bot.formatting")

    for name in (
        "build_notam_caption",
        "format_faa_activity",
        "format_road_alert",
        "format_beach_alert",
    ):
        assert hasattr(module, name), f"missing public function {name!r}"
        assert callable(getattr(module, name))


def test_formatting_does_not_pull_in_telegram_package():
    """Importing the formatting module must not import the ``telegram`` package.

    Re-import the module in isolation (after removing it and the ``telegram``
    package from ``sys.modules``) and assert the ``telegram`` package is not
    imported as a side effect. This protects the Bot_Layer decoupling required
    by Requirements 5.1 and 5.5.
    """
    import importlib

    saved = {
        name: mod
        for name, mod in list(sys.modules.items())
        if name == "telegram" or name.startswith("telegram.")
    }
    saved["starship_notam.bot.formatting"] = sys.modules.get(
        "starship_notam.bot.formatting"
    )

    try:
        for name in list(sys.modules):
            if (
                name == "telegram"
                or name.startswith("telegram.")
                or name == "starship_notam.bot.formatting"
            ):
                del sys.modules[name]

        importlib.import_module("starship_notam.bot.formatting")

        telegram_modules = [
            name
            for name in sys.modules
            if name == "telegram" or name.startswith("telegram.")
        ]
        assert telegram_modules == [], (
            "formatting import unexpectedly pulled in the Telegram API: "
            f"{telegram_modules}"
        )
    finally:
        # Restore whatever was there before so we don't disturb other tests.
        for name, mod in saved.items():
            if mod is not None:
                sys.modules[name] = mod
        importlib.import_module("starship_notam.bot.formatting")


# ---------------------------------------------------------------------------
# build_notam_caption
# ---------------------------------------------------------------------------
def test_build_notam_caption_full(sample_parsed_notam):
    """A fully populated parsed NOTAM produces a complete HTML caption."""
    caption = formatting.build_notam_caption("06_123", sample_parsed_notam)

    assert caption.startswith("<b>Новый NOTAM</b>")
    # underscores in the name are replaced with slashes
    assert "<b>Код NOTAM:</b> 06/123" in caption
    # both dates present -> arrow-separated date line, formatted dd.mm.YYYY
    assert "<b>Даты:</b>" in caption
    assert "08.07.2026" in caption
    assert "16.07.2026" in caption
    assert "→" in caption
    # details rendered as an expandable blockquote
    assert "Подробности:" in caption
    assert "<blockquote expandable>" in caption
    assert "STARSHIP SUPER HEAVY LAUNCH OPERATIONS." in caption
    assert caption.rstrip().endswith("</blockquote>")


def test_build_notam_caption_strips_json_suffix_and_underscores():
    """A ``.json`` suffix is stripped and underscores become slashes."""
    caption = formatting.build_notam_caption("A1234_25.json", {})

    assert "<b>Код NOTAM:</b> A1234/25" in caption
    assert ".json" not in caption


def test_build_notam_caption_escapes_html_in_details():
    """Angle brackets and ampersands in the E field are HTML-escaped."""
    parsed = {"E": "DANGER <script> & AT&T"}
    caption = formatting.build_notam_caption("x", parsed)

    assert "&lt;script&gt;" in caption
    assert "&amp;" in caption
    # the raw unescaped tag must not appear inside the caption body
    assert "<script>" not in caption


def test_build_notam_caption_omits_dates_when_absent():
    """When B and C are missing, no dates line is emitted."""
    caption = formatting.build_notam_caption("x", {"E": "some details"})

    assert "<b>Даты:</b>" not in caption
    assert "Подробности:" in caption


def test_build_notam_caption_replaces_percent_zero_marker():
    """The ``%0`` line-break marker is replaced with a space."""
    caption = formatting.build_notam_caption("x", {"E": "LINE1%0LINE2"})

    assert "LINE1 LINE2" in caption
    assert "%0" not in caption


def test_build_notam_caption_truncates_to_1024_with_blockquote_close():
    """Very long captions are truncated to 1024 chars, keeping blockquote valid."""
    parsed = {"E": "X" * 5000}
    caption = formatting.build_notam_caption("x", parsed)

    assert len(caption) <= 1024
    # blockquote must still be closed after truncation
    assert caption.endswith("</blockquote>")


# ---------------------------------------------------------------------------
# format_faa_activity
# ---------------------------------------------------------------------------
def test_format_faa_activity_full():
    """A FAA activity with both windows renders mission and both windows."""
    activity = {
        "mission": "Starship Flight Test",
        "primary_window": "06/24/26 0248Z-0531Z",
        "backup_window": "06/25/26 0300Z-0600Z",
    }
    msg = formatting.format_faa_activity(activity)

    assert "<b>FAA Planned Activity</b>" in msg
    assert "<b>Миссия:</b> Starship Flight Test" in msg
    assert "<b>Основное окно:</b>" in msg
    assert "<b>Запасное окно:</b>" in msg
    # date reformatted to dd.mm.YYYY and times as HH:MM with en-dash, no Z
    assert "24.06.2026 02:48–05:31 UTC" in msg
    assert "25.06.2026 03:00–06:00 UTC" in msg
    assert "Z" not in msg.replace("UTC", "")


def test_format_faa_activity_missing_mission_uses_default():
    """A missing mission falls back to the default label."""
    msg = formatting.format_faa_activity({})

    assert "<b>Миссия:</b> Unknown mission" in msg
    assert "<b>Основное окно:</b>" not in msg
    assert "<b>Запасное окно:</b>" not in msg


def test_format_faa_activity_primary_only():
    """Only a primary window renders the primary line and no backup line."""
    activity = {
        "mission": "Test",
        "primary_window": "06/24/26 0248Z-0531Z",
    }
    msg = formatting.format_faa_activity(activity)

    assert "<b>Основное окно:</b>" in msg
    assert "<b>Запасное окно:</b>" not in msg


# ---------------------------------------------------------------------------
# format_road_alert
# ---------------------------------------------------------------------------
def test_format_road_alert_full():
    """A road alert renders the translated route and formatted time window."""
    alert = {
        "origin": "Production",
        "destination": "Pad",
        "start_utc": "2026-06-25T04:59:00+00:00",
        "end_utc": "2026-06-25T10:00:00+00:00",
    }
    msg = formatting.format_road_alert(alert)

    assert "<b>🚧 Ограничение движения</b>" in msg
    # place names are translated via DEST_TRANSLATION
    assert "Starfactory" in msg
    assert "Пусковые площадки" in msg
    assert "→" in msg
    assert "<b>Время:</b>" in msg
    assert "25.06.2026 04:59 UTC" in msg
    assert "25.06.2026 10:00 UTC" in msg


def test_format_road_alert_untranslated_place_passthrough():
    """A place name not in the translation table is passed through as-is."""
    alert = {"origin": "SomewhereElse", "destination": "Port"}
    msg = formatting.format_road_alert(alert)

    assert "SomewhereElse" in msg
    assert "Порт" in msg


def test_format_road_alert_missing_places_uses_unknown_label():
    """Missing origin/destination fall back to the 'unknown' label."""
    msg = formatting.format_road_alert({})

    assert "Неизвестно" in msg
    # no time line without start/end
    assert "<b>Время:</b>" not in msg


def test_format_road_alert_handles_z_suffix_time():
    """A trailing ``Z`` on the ISO timestamps is accepted."""
    alert = {
        "origin": "Port",
        "destination": "Masseys",
        "start_utc": "2026-06-25T04:59:00Z",
        "end_utc": "2026-06-25T10:00:00Z",
    }
    msg = formatting.format_road_alert(alert)

    assert "25.06.2026 04:59 UTC" in msg
    assert "25.06.2026 10:00 UTC" in msg


# ---------------------------------------------------------------------------
# format_beach_alert
# ---------------------------------------------------------------------------
def test_format_beach_alert_with_periods_list():
    """A beach alert with a periods list renders primary and secondary periods."""
    alert = {
        "periods_json": [
            {
                "start_utc": "2026-07-08T18:00:00+00:00",
                "end_utc": "2026-07-09T04:00:00+00:00",
            },
            {
                "start_utc": "2026-07-09T18:00:00+00:00",
                "end_utc": "2026-07-10T04:00:00+00:00",
            },
        ]
    }
    msg = formatting.format_beach_alert(alert)

    assert "<b>🏖️ Перекрытие пляжа</b>" in msg
    assert "<b>Основной период:</b>" in msg
    assert "<b>Запасной период:</b>" in msg
    assert "08.07.2026 18:00 UTC" in msg
    assert "10.07.2026 04:00 UTC" in msg


def test_format_beach_alert_with_json_string_periods():
    """A periods_json provided as a JSON string is parsed and rendered."""
    alert = {
        "periods_json": (
            '[{"start_utc": "2026-07-08T18:00:00+00:00", '
            '"end_utc": "2026-07-09T04:00:00+00:00"}]'
        )
    }
    msg = formatting.format_beach_alert(alert)

    assert "<b>Основной период:</b>" in msg
    assert "08.07.2026 18:00 UTC" in msg
    assert "<b>Запасной период:</b>" not in msg


def test_format_beach_alert_fallback_to_top_level_fields():
    """With no periods, the top-level start/end fields form the primary period."""
    alert = {
        "start_utc": "2026-07-08T18:00:00+00:00",
        "end_utc": "2026-07-09T04:00:00+00:00",
    }
    msg = formatting.format_beach_alert(alert)

    assert "<b>Основной период:</b>" in msg
    assert "08.07.2026 18:00 UTC" in msg


def test_format_beach_alert_uses_raw_date_when_no_utc():
    """When only a raw_date is available, it is shown (HTML-escaped)."""
    alert = {"raw_date": "July 8 <special>"}
    msg = formatting.format_beach_alert(alert)

    assert "<b>Основной период:</b>" in msg
    assert "July 8 &lt;special&gt;" in msg


def test_format_beach_alert_invalid_json_string_is_tolerated():
    """An unparseable periods_json string does not raise; header still emitted."""
    alert = {"periods_json": "not-valid-json"}
    msg = formatting.format_beach_alert(alert)

    assert "<b>🏖️ Перекрытие пляжа</b>" in msg
    # no valid period data -> no period lines
    assert "<b>Основной период:</b>" not in msg
