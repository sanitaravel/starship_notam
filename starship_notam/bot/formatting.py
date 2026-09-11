"""Message formatting for Telegram posts.

Pure formatting functions extracted from the flat ``telegram_bot.py`` module.
This module produces HTML-formatted caption/message strings from plain Python
dictionaries. It performs NO network I/O and does NOT import the Telegram API.

Only standard library modules are used.

Public functions:
    build_notam_caption(name, parsed) -> str
    format_faa_activity(activity) -> str
    format_road_alert(alert) -> str
    format_beach_alert(alert) -> str
    format_fcc_els_application(app) -> str
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from urllib.parse import urljoin


# Base used to resolve the root-relative FCC ELS detail links (e.g.
# "/oetcf/els/reports/STA_Print.cfm?..") scraped into ``current_detail_url``
# into absolute, clickable URLs. Kept local so this module stays stdlib-only
# and free of the config/network layer.
_FCC_ELS_BASE_URL = "https://apps.fcc.gov/oetcf/els/reports/"


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


def format_faa_activity(activity: dict) -> str:
    """Format an FAA planned activity dict into an HTML message string."""

    def convert_faa_time(s: str):
        # "06/24/26 0248Z-0531Z"
        date_part, times = s.split()
        start, end = times.split("-")

        dt = datetime.strptime(date_part, "%m/%d/%y")

        start_fmt = f"{start[:2]}:{start[2:]}"[:-1]  # remove trailing Z
        end_fmt = f"{end[:2]}:{end[2:]}"[:-1]  # remove trailing Z

        return f"{dt.strftime('%d.%m.%Y')} {start_fmt}–{end_fmt} UTC"

    mission = activity.get("mission", "Unknown mission")
    primary = activity.get("primary_window", "")
    backup = activity.get("backup_window", "")

    parts = []
    parts.append("<b>FAA Planned Activity</b>")
    parts.append(f"<b>Миссия:</b> {html.escape(mission)}")

    if primary:
        parts.append(
            f"<b>Основное окно:</b> {html.escape(convert_faa_time(primary))}")

    if backup:
        parts.append(
            f"<b>Запасное окно:</b> {html.escape(convert_faa_time(backup))}")

    return "\n\n".join(parts)


def format_road_alert(alert: dict) -> str:
    """Format a road-delay alert dict into an HTML message string."""

    def fmt_time(iso_str: str):
        # expects ISO UTC like "2026-06-25T04:59:00+00:00"
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%d.%m.%Y %H:%M UTC")

    origin = translate_place(alert.get("origin"))
    destination = translate_place(alert.get("destination"))

    parts = []
    parts.append("<b>🚧 Ограничение движения</b>")
    parts.append(f"<b>Маршрут:</b> {html.escape(origin)} → {html.escape(destination)}")

    if alert.get("start_utc") and alert.get("end_utc"):
        parts.append(
            f"<b>Время:</b> {html.escape(fmt_time(alert['start_utc']))} – {html.escape(fmt_time(alert['end_utc']))}"
        )

    return "\n\n".join(parts)


def format_beach_alert(alert: dict) -> str:
    """Format a beach-closure alert dict into an HTML message string."""

    def fmt_time(iso_str: str):
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%d.%m.%Y %H:%M UTC")

    def period_text(period: dict) -> str:
        start_utc = period.get("start_utc")
        end_utc = period.get("end_utc")
        if start_utc and end_utc:
            return f"{fmt_time(start_utc)} – {fmt_time(end_utc)}"

        raw_date = period.get("raw_date")
        return html.escape(str(raw_date)) if raw_date else ""

    periods = alert.get("periods_json")

    if isinstance(periods, str):
        try:
            periods = json.loads(periods)
        except Exception:
            periods = []
    if not isinstance(periods, list):
        periods = []

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

    return "\n\n".join(parts)


def format_fcc_els_application(app: dict) -> str:
    """Format an FCC ELS application dict into a Russian-language HTML string.

    All user-supplied text is passed through ``html.escape``. Dates are
    displayed in ``dd.mm.yyyy`` style. The expandable blockquote contains the
    "purpose of operation" and the STA "Explanation" detail fields (parsed from
    ``detail_json``, which may be a dict or a JSON string), each under its own
    label. A link to the source FCC ELS application (resolved from
    ``current_detail_url``) is appended when available. Performs no network I/O;
    uses standard library only.
    """

    def fmt_date(value: str) -> str:
        # FCC ELS supplies dates as mm/dd/yyyy (e.g. "08/12/2026"); render them
        # as dd.mm.yyyy. Leave anything that doesn't match untouched.
        value = value.strip()
        if not value:
            return ""
        try:
            return datetime.strptime(value, "%m/%d/%Y").strftime("%d.%m.%Y")
        except ValueError:
            return value

    # Keys under which the free-text values are stored in the parsed detail dict
    # (they match the STA_Print form's field labels / the parser's Explanation
    # key).
    purpose_label = "Please explain the purpose of operation"
    explanation_label = "Explanation"

    parts = []
    parts.append("<b>Новая заявка FCC ELS</b>")

    applicant_name = str(app.get("applicant_name") or "")
    file_number = str(app.get("file_number") or "")
    call_sign = str(app.get("call_sign") or "")
    status = str(app.get("status") or "")
    receipt_date = fmt_date(str(app.get("receipt_date") or ""))
    status_date = fmt_date(str(app.get("status_date") or ""))

    parts.append(f"<b>Заявитель:</b> {html.escape(applicant_name)}")
    parts.append(f"<b>Номер дела:</b> {html.escape(file_number)}")
    if call_sign:
        parts.append(f"<b>Позывной:</b> {html.escape(call_sign)}")
    parts.append(f"<b>Статус:</b> {html.escape(status)}")
    parts.append(f"<b>Дата получения:</b> {html.escape(receipt_date)}")
    parts.append(f"<b>Дата статуса:</b> {html.escape(status_date)}")

    # Detail fields: accept either a dict or a JSON string (mirrors how
    # format_beach_alert handles periods_json).
    detail = app.get("detail_json")
    if isinstance(detail, str):
        try:
            detail = json.loads(detail)
        except Exception:
            detail = {}
    if not isinstance(detail, dict):
        detail = {}

    # Build the expandable blockquote from the purpose-of-operation and the STA
    # explanation, each under its own bold label. Include only the fields that
    # are present.
    purpose_value = str(detail.get(purpose_label) or "").strip()
    explanation_value = str(detail.get(explanation_label) or "").strip()

    bq_lines = []
    if purpose_value:
        bq_lines.append(
            f"<b>Цель эксплуатации:</b> {html.escape(purpose_value)}"
        )
    if explanation_value:
        bq_lines.append(
            f"<b>Обоснование:</b> {html.escape(explanation_value)}"
        )

    if bq_lines:
        expandable_bq = (
            "<blockquote expandable>"
            + "\n\n".join(bq_lines)
            + "</blockquote>"
        )
        parts.append(expandable_bq)

    # Append a link to the source FCC ELS application when available. The
    # scraped ``current_detail_url`` is typically root-relative, so resolve it
    # against the ELS reports base to produce an absolute, clickable URL.
    detail_url = str(app.get("current_detail_url") or "").strip()
    if detail_url:
        absolute_url = urljoin(_FCC_ELS_BASE_URL, detail_url)
        parts.append(
            f'<a href="{html.escape(absolute_url, quote=True)}">'
            "Открыть заявку</a>"
        )

    return "\n\n".join(parts)


def build_notam_caption(name: str, parsed: dict) -> str:
    """Build an HTML caption for a NOTAM image from a parsed NOTAM dict."""
    parts = []
    parts.append('<b>Новый NOTAM</b>')
    # display name/title: strip any trailing .json then replace underscores
    raw_name = str(name or '')
    if raw_name.lower().endswith('.json'):
        raw_name = raw_name[:-5]
    display_name = raw_name.replace('_', '/')
    parts.append(f"<b>Код NOTAM:</b> {html.escape(display_name)}")

    def _fmt_dt(s):
        if not s:
            return ''
        try:
            s_str = str(s).strip()
            if s_str.endswith('Z'):
                s_str = s_str[:-1]
            s_iso = s_str.replace('T', ' ')
            try:
                dt = datetime.fromisoformat(s_iso)
                if dt.tzinfo is not None:
                    dt_utc = dt.astimezone(timezone.utc)
                else:
                    dt_utc = dt
                return dt_utc.strftime('%d.%m.%Y %H:%M UTC')
            except Exception:
                return s_iso
        except Exception:
            return str(s)

    # Dates (B and C)
    b_fmt = _fmt_dt(parsed.get('B') or '')
    c_fmt = _fmt_dt(parsed.get('C') or '')
    if b_fmt or c_fmt:
        parts.append(f"<b>Даты:</b> {html.escape(b_fmt)} → {html.escape(c_fmt)}")

    # Details (E) as blockquote
    if parsed.get('E'):
        details_raw = parsed.get('E')
        details_clean = str(details_raw).replace('%0', ' ')
        details_escaped = html.escape(details_clean)
        parts.append('Подробности:')
        expandable_bq = f"<blockquote expandable>{details_escaped}</blockquote>"
        parts.append(expandable_bq)

    caption = '\n\n'.join(parts)
    if len(caption) > 1024:
        closing = '</blockquote>'
        if '<blockquote' in caption:
            truncated = caption[:1024 - len(closing)]
            return truncated + closing
        return caption[:1024]
    return caption
