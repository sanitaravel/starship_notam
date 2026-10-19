"""USCG Broadcast Notice to Mariners messages."""

from __future__ import annotations

import html
from datetime import datetime

from src.bot.formatting._common import TAG_COMMON, hashtag_line


_TAGS_BNM = (TAG_COMMON, "#BNM", "#Starship")

# Coast Guard districts by the BNM number prefix (renamed in 2025: District 8
# became Heartland, District 7 Southeast).
_DISTRICTS = {
    "CGD-H": "Округ Heartland",
    "CCGD8": "Округ Heartland",
    "CGD-SE": "Округ Southeast",
    "CCGD-SE": "Округ Southeast",
    "CCGD7": "Округ Southeast",
}

# Russian names of the hazard-area labels; an unlabelled area is a hazard area.
_AREA_LABELS = {
    "HIGH RISK HAZARD AREA": "зона высокого риска",
    "HAZARD AREA": "опасная зона",
}

# Outcomes stated by cancellations; others are shown as written.
_OUTCOMES = {
    "SUCCESSFUL LAUNCH": "успешный запуск",
    "RESCHEDULED": "запуск перенесён",
    "SCRUBBED": "запуск отменён",
    "POSTPONED": "запуск отложен",
}

# At most this many windows are listed; a photo caption is limited to 1024
# characters.
_WINDOW_LIMIT = 10


def _field(item: dict, key: str) -> str:
    return str(item.get(key) or "").strip()


def _district(bnm_id: str) -> str:
    return _DISTRICTS.get(bnm_id.split()[0].upper(), "") if bnm_id else ""


def _utc(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def format_bnm_window(start: str, end: str) -> str:
    """``("2026-09-28T12:15:00Z", "2026-09-28T14:14:00Z")`` -> ``28.09.2026 12:15–14:14``.

    The end shows its date only when it falls on another day.
    """
    s, e = _utc(start), _utc(end)
    if not s or not e:
        return f"{start} – {end}"
    tail = e.strftime("%H:%M") if e.date() == s.date() else e.strftime("%d.%m.%Y %H:%M")
    return f"{s:%d.%m.%Y %H:%M}–{tail}"


def _link(url: str, text: str) -> str:
    return f'<a href="{html.escape(url, quote=True)}">{html.escape(text)}</a>'


def _mission(item: dict) -> str:
    flight = _field(item, "flight")
    return f"Starship Flight {flight}" if flight else _field(item, "mission").title()


def _number_line(item: dict, label: str, bnm_id: str) -> str:
    district = _district(bnm_id)
    return f"<b>{label}:</b> {html.escape(bnm_id)}" + (f" ({district})" if district else "")


def _format_safety(item: dict) -> list[str]:
    parts = ["<b>⚓ Оповещение мореплавателям USCG</b>"]
    mission = _mission(item)
    if mission:
        parts.append(f"<b>{html.escape(mission)}</b>")

    details = [_number_line(item, "Номер", _field(item, "bnm_id"))]
    region = _field(item, "region")
    if region:
        details.append(f"<b>Район:</b> {html.escape(region)}")
    labels = []
    for letter, area in zip("ABCDEFGH", item.get("areas") or []):
        label = str(area.get("label") or "").upper()
        labels.append(f"{letter} — {_AREA_LABELS.get(label, label.lower() or 'опасная зона')}")
    if labels:
        details.append(f"<b>Зоны:</b> {html.escape(', '.join(labels))}")
    parts.append("\n".join(details))

    windows = [w for w in item.get("windows") or [] if len(w) == 2]
    if windows:
        lines = ["<b>Окна опасности (UTC):</b>"]
        lines += [f"• {html.escape(format_bnm_window(*w))}" for w in windows[:_WINDOW_LIMIT]]
        if len(windows) > _WINDOW_LIMIT:
            lines.append(f"… и ещё {len(windows) - _WINDOW_LIMIT}")
        parts.append("\n".join(lines))
    return parts


def _format_cancellation(item: dict) -> list[str]:
    parts = ["<b>⚓ Оповещение мореплавателям USCG отменено</b>"]
    details = [_number_line(item, "Отменено", _field(item, "cancels") or _field(item, "bnm_id"))]
    outcome = _field(item, "outcome")
    if outcome:
        mission, _, result = outcome.rpartition(",")
        result = result.strip().upper()
        if result in _OUTCOMES:
            subject = _mission(item) or mission.strip().title()
            text = f"{subject} — {_OUTCOMES[result]}" if subject else _OUTCOMES[result]
        else:
            text = outcome
        details.append(f"<b>Итог:</b> {html.escape(text)}")
    parts.append("\n".join(details))
    return parts


def format_uscg_bnm_notice(item: dict) -> str:
    """Format a Starship BNM into a Russian HTML string.

    A safety notice (sent as the caption of its hazard-area map) shows the
    flight, the BNM number and district, the region, the lettered areas and
    the UTC hazard windows. A cancellation shows the cancelled BNM and the
    outcome the Coast Guard states (e.g. a successful launch). Both link the
    bulletin. All site-supplied text is passed through ``html.escape``.
    """
    if _field(item, "kind") == "CANCELLATION" or _field(item, "cancels"):
        parts = _format_cancellation(item)
    else:
        parts = _format_safety(item)

    link = _field(item, "link")
    if link:
        parts.append(_link(link, "Текст оповещения"))
    flight = _field(item, "flight")
    parts.append(hashtag_line(*_TAGS_BNM, f"#Flight{flight}" if flight else ""))
    return "\n\n".join(parts)
