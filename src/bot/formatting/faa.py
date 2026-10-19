"""FAA planned-activity and launch-license messages."""

from __future__ import annotations

import html
from datetime import datetime
from urllib.parse import urljoin

from src.bot.formatting._common import TAG_COMMON, coerce_json, hashtag_line


_TAGS_FAA_ACTIVITY = (TAG_COMMON, "#FAA", "#Запуск")
_TAGS_FAA_LICENSE = (TAG_COMMON, "#FAA", "#Лицензия")


# Base used to build a clickable link to the FAA DRS document viewer from a
# license record's ``doc_unique_id``. Kept local so this module stays
# stdlib-only and free of the config/network layer.
_FAA_DRS_VIEWER_BASE_URL = "https://drs.faa.gov/browse/excelExternalWindow/"


# Ordered "Document Details" labels (left column) mapped to their Russian
# display labels for the launch-license notification. Order controls the
# rendered order. Labels match the keys produced by the license parser.
_FAA_LICENSE_FIELD_LABELS: list[tuple[str, str]] = [
    ("License Number", "Номер лицензии"),
    ("Status", "Статус"),
    ("Revision Number", "Номер редакции"),
    ("Document Issue Date", "Дата выдачи"),
    ("Document Expiration Date", "Дата окончания"),
    ("Company", "Компания"),
    ("Vehicles", "Аппараты"),
    ("Location", "Место"),
    ("Document Type", "Тип документа"),
    ("Service/Office", "Служба/офис"),
    ("Office of Primary Responsibility", "Ответственный офис"),
    ("CFR Part Reference", "Ссылка на CFR (Part)"),
    ("CFR Subpart/Appendix Reference", "Ссылка на CFR (Subpart/Appendix)"),
    ("CFR Section Reference", "Ссылка на CFR (Section)"),
]


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

    parts.append(hashtag_line(*_TAGS_FAA_ACTIVITY))

    return "\n\n".join(parts)


def format_faa_license(item: dict) -> str:
    """Format a FAA DRS launch-license record into a Russian HTML string.

    Renders the tracked "Document Details" panel: the header reflects whether
    this is a newly tracked license or an update to an existing one (via the
    ``is_new`` flag set by the repository), followed by the detail fields (only
    those with a value) in a fixed, readable order, and a link to the source
    DRS document viewer.

    All user-supplied text is passed through ``html.escape``. The ``details``
    field may be a dict or a JSON string (mirroring how ``format_beach_alert``
    and ``format_fcc_els_application`` tolerate serialized sub-payloads).
    Performs no network I/O; uses the standard library only.
    """
    details = coerce_json(item.get("details"), {})

    # Fall back to the flat columns for the headline fields when ``details`` is
    # missing an entry (both are populated by the parser, but stay defensive).
    def _field(label: str, fallback_key: str = "") -> str:
        value = details.get(label)
        if (value is None or str(value).strip() == "") and fallback_key:
            value = item.get(fallback_key)
        return "" if value is None else str(value).strip()

    is_new = bool(item.get("is_new", True))
    parts = []
    if is_new:
        parts.append("<b>🚀 Лицензия на запуск (FAA)</b>")
    else:
        parts.append("<b>🚀 Изменения в лицензии на запуск (FAA)</b>")

    _column_fallbacks = {
        "License Number": "doc_number",
        "Status": "status",
        "Revision Number": "revision_number",
        "Document Issue Date": "issue_date",
        "Document Expiration Date": "expiration_date",
    }

    for label, ru_label in _FAA_LICENSE_FIELD_LABELS:
        value = _field(label, _column_fallbacks.get(label, ""))
        if not value:
            continue
        parts.append(f"<b>{ru_label}:</b> {html.escape(value)}")

    # Link to the source DRS document viewer, built from the stable document id.
    doc_id = str(item.get("doc_unique_id") or "").strip()
    if doc_id:
        viewer_url = urljoin(_FAA_DRS_VIEWER_BASE_URL, doc_id)
        parts.append(
            f'<a href="{html.escape(viewer_url, quote=True)}">'
            "Открыть документ</a>"
        )

    parts.append(hashtag_line(*_TAGS_FAA_LICENSE))

    return "\n\n".join(parts)
