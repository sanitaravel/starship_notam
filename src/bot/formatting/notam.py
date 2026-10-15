"""NOTAM photo captions."""

from __future__ import annotations

import html

from src.bot.formatting._common import TAG_COMMON, hashtag_line
from src.parsers.notam_time import parse_notam_time
from src.parsers.schedule import parse_notam_windows_with_dates


_TAGS_NOTAM = (TAG_COMMON, "#NOTAM")

# Telegram's maximum photo caption length.
_CAPTION_LIMIT = 1024


def _sanitize_tag(value: str) -> str:
    """Turn arbitrary text into a single ``#Tag`` token.

    Keeps letters and digits, drops everything else (Telegram hashtags cannot
    contain spaces or punctuation). Returns an empty string when nothing usable
    remains, so callers can filter it out.
    """
    if not value:
        return ""
    cleaned = "".join(ch for ch in str(value) if ch.isalnum())
    return f"#{cleaned}" if cleaned else ""


def build_notam_caption(name: str, parsed: dict) -> str:
    """Build an HTML caption for a NOTAM image from a parsed NOTAM dict."""
    parts = []
    parts.append('<b>Новый NOTAM</b>')
    # Stored names use '_' in place of '/' (A0669_26 -> A0669/26).
    display_name = str(name or '').replace('_', '/')
    parts.append(f"<b>Код NOTAM:</b> {html.escape(display_name)}")

    def _fmt_dt(s):
        dt = parse_notam_time(s)
        if dt is not None:
            return dt.strftime('%d.%m.%Y %H:%M UTC')
        return str(s or '').strip().removesuffix('Z').replace('T', ' ')

    # Dates. Prefer the same per-day schedule breakdown used on the image
    # (parsed from field D), so daily/multi-day NOTAMs list each active date
    # with its window instead of a single "B → C" span. Fall back to the
    # B → C line when D is empty or unparseable.
    start_dt = parse_notam_time(parsed.get('B'))
    end_dt = parse_notam_time(parsed.get('C'))
    windows = parse_notam_windows_with_dates(
        parsed.get('D'), parsed.get('E'), start_dt, end_dt
    )
    if windows:
        window_lines = "\n".join(html.escape(w) for w in windows)
        parts.append(f"<b>Даты (UTC):</b>\n{window_lines}")
    else:
        b_fmt = _fmt_dt(parsed.get('B') or '')
        c_fmt = _fmt_dt(parsed.get('C') or '')
        if b_fmt or c_fmt:
            parts.append(
                f"<b>Даты:</b> {html.escape(b_fmt)} → {html.escape(c_fmt)}"
            )

    # Hashtags for channel search: the common + NOTAM tags plus a tag derived
    # from the NOTAM code (e.g. "B1882/26" -> "#B188226") so a specific NOTAM
    # is searchable. Always kept, even when the details are trimmed.
    tag_line = hashtag_line(*_TAGS_NOTAM, _sanitize_tag(display_name))
    head = '\n\n'.join(parts)

    details = str(parsed.get('E') or '').replace('%0', ' ')
    if not details:
        return _fit_caption(f"{head}\n\n{tag_line}")

    def with_details(text: str) -> str:
        return (
            f"{head}\n\nПодробности:\n\n"
            f"<blockquote expandable>{html.escape(text)}</blockquote>"
            f"\n\n{tag_line}"
        )

    caption = with_details(details)
    if len(caption) <= _CAPTION_LIMIT:
        return caption

    # Too long (Telegram caption limit): trim the *unescaped* details so the
    # cut never lands inside an HTML entity like "&amp;" or a tag, then escape
    # and wrap them again. Binary search for the longest prefix that fits.
    lo, hi = 0, len(details)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if len(with_details(details[:mid].rstrip() + '…')) <= _CAPTION_LIMIT:
            lo = mid
        else:
            hi = mid - 1
    if lo == 0:
        return _fit_caption(f"{head}\n\n{tag_line}")
    return with_details(details[:lo].rstrip() + '…')


def _fit_caption(caption: str) -> str:
    """Hard-trim a caption that has no blockquote to the Telegram limit.

    Only reached when the header alone is too long, which needs a name or
    schedule of hundreds of characters; the cut happens on a line boundary so
    no tag or entity is split.
    """
    if len(caption) <= _CAPTION_LIMIT:
        return caption
    lines = caption.split('\n')
    tag_line = lines[-1]
    kept: list[str] = []
    for line in lines[:-1]:
        if len('\n'.join(kept + [line])) + len('\n\n') + len(tag_line) > _CAPTION_LIMIT:
            break
        kept.append(line)
    return '\n'.join(kept).rstrip() + '\n\n' + tag_line
