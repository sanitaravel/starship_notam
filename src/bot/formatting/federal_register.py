"""FAA Federal Register document messages."""

from __future__ import annotations

import html
from datetime import datetime

from src.bot.formatting._common import TAG_COMMON, hashtag_line


_TAGS_FEDERAL_REGISTER = (TAG_COMMON, "#FederalRegister", "#FAA")


# Russian labels for Federal Register document types; unknown types are shown
# as the site names them.
_FEDERAL_REGISTER_TYPES = {
    "Notice": "Уведомление",
    "Rule": "Правило",
    "Proposed Rule": "Проект правила",
    "Presidential Document": "Документ президента",
}

# Federal Register abstracts can run to several paragraphs; longer ones are
# cut at a word boundary (the full text is one click away).
_FEDERAL_REGISTER_ABSTRACT_LIMIT = 600


def _fmt_iso_date(value: str) -> str:
    """Format an ISO date (``2026-10-14``) as ``14.10.2026``; other text is kept."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d.%m.%Y")
    except ValueError:
        return value


def _trim_words(text: str, limit: int) -> str:
    """Cut ``text`` to at most ``limit`` characters at a word boundary, adding "…"."""
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:.")
    return cut + "…"


def format_federal_register_document(item: dict) -> str:
    """Format a new FAA Federal Register document into a Russian HTML string.

    Shows the document type, title, publication date, the comment deadline
    (if the document has one), a trimmed abstract and links to the HTML and
    PDF versions. All site-supplied text is passed through ``html.escape``.
    """
    def _field(key: str) -> str:
        return str(item.get(key) or "").strip()

    doc_type = _field("doc_type")
    header = "📄 Federal Register: новый документ FAA"
    if doc_type:
        header += f" ({_FEDERAL_REGISTER_TYPES.get(doc_type, doc_type)})"
    parts = [f"<b>{html.escape(header)}</b>"]

    title = _field("title")
    if title:
        parts.append(f"<b>{html.escape(title)}</b>")

    dates = []
    published = _field("publication_date")
    if published:
        dates.append(f"<b>Опубликован:</b> {html.escape(_fmt_iso_date(published))}")
    comments_close = _field("comments_close_on")
    if comments_close:
        dates.append(
            f"<b>Комментарии до:</b> {html.escape(_fmt_iso_date(comments_close))}"
        )
    if dates:
        parts.append("\n".join(dates))

    abstract = _field("abstract")
    if abstract:
        parts.append(html.escape(_trim_words(abstract, _FEDERAL_REGISTER_ABSTRACT_LIMIT)))

    links = []
    html_url = _field("html_url")
    if html_url:
        links.append(f'<a href="{html.escape(html_url, quote=True)}">Открыть документ</a>')
    pdf_url = _field("pdf_url")
    if pdf_url:
        links.append(f'<a href="{html.escape(pdf_url, quote=True)}">PDF</a>')
    if links:
        parts.append(" | ".join(links))

    parts.append(hashtag_line(*_TAGS_FEDERAL_REGISTER))

    return "\n\n".join(parts)
