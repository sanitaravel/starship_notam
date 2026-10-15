"""FAA/USCG Regulations.gov document messages."""

from __future__ import annotations

import html
from datetime import datetime
from zoneinfo import ZoneInfo

from src.bot.formatting._common import TAG_COMMON, hashtag_line


_TAGS_REGULATIONS_GOV = (TAG_COMMON, "#RegulationsGov")

# Regulations.gov dates are midnight / 23:59:59 US Eastern time written in UTC
# (a comment period ending "2026-12-01T04:59:59Z" closes on 30 November).
_EASTERN = ZoneInfo("America/New_York")

# Russian labels for Regulations.gov document types; unknown types are shown
# as the site names them.
_DOCUMENT_TYPES = {
    "Notice": "Уведомление",
    "Rule": "Правило",
    "Proposed Rule": "Проект правила",
    "Other": "Документ",
    "Supporting & Related Material": "Сопутствующий материал",
}

# At most this many files are linked; the rest are on the document page.
_FILE_LIMIT = 5
_FILE_TITLE_LIMIT = 90


def _eastern(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(_EASTERN)
    except ValueError:
        return None


def _fmt_date(value: str) -> str:
    """``2026-10-14T04:00:00Z`` -> ``14.10.2026`` (Eastern date); other text is kept."""
    dt = _eastern(value)
    return dt.strftime("%d.%m.%Y") if dt else value


def _fmt_deadline(value: str) -> str:
    """``2026-12-01T04:59:59Z`` -> ``30.11.2026 23:59 ET``; other text is kept."""
    dt = _eastern(value)
    return dt.strftime("%d.%m.%Y %H:%M ET") if dt else value


def _trim(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _link(url: str, text: str) -> str:
    return f'<a href="{html.escape(url, quote=True)}">{html.escape(text)}</a>'


def format_regulations_gov_document(item: dict) -> str:
    """Format a new Regulations.gov document into a Russian HTML string.

    Shows the agency and document type, the title, the posting date, the
    comment deadline (if the document has one), links to the document's files
    (``item["files"]``, as listed by
    :func:`src.parsers.regulations_gov_parser.parse_regulations_gov_files`)
    and to the document, its docket and its Federal Register version. All
    site-supplied text is passed through ``html.escape``.
    """
    def _field(key: str) -> str:
        return str(item.get(key) or "").strip()

    document_id = _field("document_id")
    agency = _field("agency_id")
    header = "🗂 Regulations.gov: новый документ"
    if agency:
        header += f" {agency}"
    document_type = _field("document_type")
    if document_type:
        header += f" ({_DOCUMENT_TYPES.get(document_type, document_type)})"
    parts = [f"<b>{html.escape(header)}</b>"]

    title = _field("title")
    if title:
        parts.append(f"<b>{html.escape(title)}</b>")

    details = []
    subtype = _field("subtype")
    if subtype:
        details.append(f"<b>Вид:</b> {html.escape(subtype)}")
    docket_id = _field("docket_id")
    if docket_id:
        details.append(f"<b>Докет:</b> {html.escape(docket_id)}")
    posted = _field("posted_date")
    if posted:
        details.append(f"<b>Опубликован:</b> {html.escape(_fmt_date(posted))}")
    comment_end = _field("comment_end_date")
    if comment_end:
        details.append(f"<b>Комментарии до:</b> {html.escape(_fmt_deadline(comment_end))}")
    if details:
        parts.append("\n".join(details))

    files = [f for f in item.get("files") or [] if isinstance(f, dict) and f.get("url")]
    if files:
        lines = []
        for f in files[:_FILE_LIMIT]:
            name = _trim(str(f.get("title") or "").strip(), _FILE_TITLE_LIMIT) or "Документ"
            fmt = str(f.get("format") or "").strip().upper()
            lines.append("📎 " + _link(str(f["url"]), name) + (f" ({html.escape(fmt)})" if fmt else ""))
        if len(files) > _FILE_LIMIT:
            lines.append(f"…и ещё {len(files) - _FILE_LIMIT} на странице документа")
        parts.append("\n".join(lines))

    links = []
    if document_id:
        links.append(
            _link(f"https://www.regulations.gov/document/{document_id}", "Открыть документ")
        )
    if docket_id:
        links.append(_link(f"https://www.regulations.gov/docket/{docket_id}", "Докет"))
    fr_doc_num = _field("fr_doc_num")
    if fr_doc_num:
        links.append(_link(f"https://www.federalregister.gov/d/{fr_doc_num}", "Federal Register"))
    if links:
        parts.append(" | ".join(links))

    agency_tag = f"#{agency}" if agency.isalnum() else ""
    parts.append(hashtag_line(*_TAGS_REGULATIONS_GOV, agency_tag))

    return "\n\n".join(parts)
