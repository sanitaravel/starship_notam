"""COMPASS "Master Slide Deck" file messages."""

from __future__ import annotations

import html
from urllib.parse import quote

from src.bot.formatting._common import TAG_COMMON, hashtag_line


_TAGS_COMPASS = (TAG_COMMON, "#COMPASS")


# Links for COMPASS "Master Slide Deck" posts: the file itself (by fileuuid)
# and the list page. Kept local so this module stays stdlib-only.
_COMPASS_FILE_URL = "https://compass.atfm.aero/public_svcdynamic/getfile?download=false&fileuuid="
_COMPASS_PAGE_URL = "https://compass.atfm.aero/vpublic_anspdetail.jsp?view=3"


def format_compass_file(item: dict) -> str:
    """Format a new COMPASS "Master Slide Deck" file into a Russian HTML string.

    Shows the file name and upload time (as the site prints it), a direct
    link to the file and a link to the list page. All site-supplied text is
    passed through ``html.escape``.
    """
    parts = ["<b>📊 Новый файл в COMPASS (Master Slide Deck)</b>"]

    filename = str(item.get("filename") or "").strip()
    if filename:
        parts.append(f"<b>Файл:</b> {html.escape(filename)}")
    uploaded_at = str(item.get("uploaded_at") or "").strip()
    if uploaded_at:
        parts.append(f"<b>Загружен:</b> {html.escape(uploaded_at)}")

    links = []
    file_uuid = str(item.get("file_uuid") or "").strip()
    if file_uuid:
        file_url = _COMPASS_FILE_URL + quote(file_uuid)
        links.append(f'<a href="{html.escape(file_url, quote=True)}">Скачать файл</a>')
    links.append(f'<a href="{html.escape(_COMPASS_PAGE_URL, quote=True)}">Все файлы</a>')
    parts.append(" | ".join(links))

    parts.append(hashtag_line(*_TAGS_COMPASS))

    return "\n\n".join(parts)
