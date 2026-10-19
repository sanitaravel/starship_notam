"""Starbase road-delay and beach-closure alerts."""

from __future__ import annotations

import html

from src.bot.formatting._common import (
    TAG_COMMON,
    coerce_json,
    fmt_utc,
    hashtag_line,
)


_TAGS_ROAD = (TAG_COMMON, "#Дорога", "#Перекрытие")
_TAGS_BEACH = (TAG_COMMON, "#Пляж", "#Перекрытие")


# Translation table for Starbase place names (used by road alert formatting).
DEST_TRANSLATION = {
    "Production": "Starfactory",
    "Pad": "Пусковые площадки",
    "Masseys": "Мэссис",
    "Huddleston": "Хаддлстон",
    "Port": "Порт",
}


def translate_place(name: str) -> str:
    """Translate a Starbase place name to its display label."""
    if not name:
        return "Неизвестно"
    return DEST_TRANSLATION.get(name, name)


def format_road_alert(alert: dict) -> str:
    """Format a road-delay alert dict into an HTML message string."""

    origin = translate_place(alert.get("origin"))
    destination = translate_place(alert.get("destination"))

    parts = []
    parts.append("<b>🚧 Ограничение движения</b>")
    parts.append(f"<b>Маршрут:</b> {html.escape(origin)} → {html.escape(destination)}")

    if alert.get("start_utc") and alert.get("end_utc"):
        parts.append(
            f"<b>Время:</b> {html.escape(fmt_utc(alert['start_utc']))} – {html.escape(fmt_utc(alert['end_utc']))}"
        )

    parts.append(hashtag_line(*_TAGS_ROAD))

    return "\n\n".join(parts)


def format_beach_alert(alert: dict) -> str:
    """Format a beach-closure alert dict into an HTML message string."""

    def period_text(period: dict) -> str:
        start_utc = period.get("start_utc")
        end_utc = period.get("end_utc")
        if start_utc and end_utc:
            return f"{fmt_utc(start_utc)} – {fmt_utc(end_utc)}"

        raw_date = period.get("raw_date")
        return html.escape(str(raw_date)) if raw_date else ""

    periods = coerce_json(alert.get("periods_json"), [])

    primary_period = periods[0] if periods else {
        "start_utc": alert.get("start_utc"),
        "end_utc": alert.get("end_utc"),
        "raw_date": alert.get("raw_date"),
    }
    secondary_period = periods[1] if len(periods) > 1 else None

    parts = []
    parts.append("<b>🏖️ Перекрытие пляжа</b>")

    primary_text = period_text(primary_period)
    if primary_text:
        parts.append(f"<b>Основной период:</b> {primary_text}")

    if secondary_period:
        secondary_text = period_text(secondary_period)
        if secondary_text:
            parts.append(f"<b>Запасной период:</b> {secondary_text}")

    parts.append(hashtag_line(*_TAGS_BEACH))

    return "\n\n".join(parts)
