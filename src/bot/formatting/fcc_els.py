"""FCC ELS experimental-license application messages."""

from __future__ import annotations

import html
from datetime import datetime
from urllib.parse import urljoin

from src.bot.formatting._common import TAG_COMMON, coerce_json, hashtag_line


_TAGS_FCC = (TAG_COMMON, "#FCC", "#Заявка")


# Base used to resolve the root-relative FCC ELS detail links (e.g.
# "/oetcf/els/reports/STA_Print.cfm?..") scraped into ``current_detail_url``
# into absolute, clickable URLs. Kept local so this module stays stdlib-only
# and free of the config/network layer.
_FCC_ELS_BASE_URL = "https://apps.fcc.gov/oetcf/els/reports/"


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

    detail = coerce_json(app.get("detail_json"), {})

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

    parts.append(hashtag_line(*_TAGS_FCC))

    return "\n\n".join(parts)
