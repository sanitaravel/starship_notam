"""SpaceX Starship documentary episode messages."""

from __future__ import annotations

import html

from src.bot.formatting._common import TAG_COMMON, fmt_utc, hashtag_line


_TAGS_STARSHIP_DOC = (TAG_COMMON, "#Starship", "#Документалка")


def _duration(seconds: int) -> str:
    """``1270`` -> ``"21 мин 10 с"``; an hour or more -> ``"1 ч 02 мин"``."""
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours} ч {minutes:02d} мин"
    return f"{minutes} мин {secs:02d} с" if minutes else f"{secs} с"


def format_starship_documentary(item: dict) -> str:
    """Format a new Starship documentary episode into a Russian HTML string.

    *item* holds ``episode``, ``duration_seconds``, ``published_at`` (ISO UTC),
    ``master_url`` and ``playlist_url``. The links are HLS playlists, which
    open in Safari or VLC (SpaceX has no verifiable watch page).
    """
    parts = [
        "<b>🎬 SpaceX: новый эпизод документального сериала о Starship</b>",
        "",
        f"<b>Эпизод {html.escape(str(item.get('episode') or ''))}</b>",
    ]
    seconds = item.get("duration_seconds") or 0
    if seconds > 0:
        parts.append(f"<b>Длительность:</b> {_duration(int(seconds))}")
    published = item.get("published_at") or ""
    if published:
        try:
            parts.append(f"<b>Опубликован:</b> {fmt_utc(published)}")
        except ValueError:
            parts.append(f"<b>Опубликован:</b> {html.escape(published)}")

    links = []
    if item.get("master_url"):
        links.append(f'<a href="{html.escape(item["master_url"])}">Смотреть (HLS)</a>')
    if item.get("playlist_url"):
        links.append(f'<a href="{html.escape(item["playlist_url"])}">4K</a>')
    if links:
        parts += ["", " | ".join(links), "<i>HLS открывается в Safari и VLC</i>"]

    parts += ["", hashtag_line(*_TAGS_STARSHIP_DOC)]
    return "\n".join(parts)
