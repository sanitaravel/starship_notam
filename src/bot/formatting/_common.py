"""Helpers shared by the per-source formatters."""

from __future__ import annotations

import json
from datetime import datetime


# Hashtags appended to each message so the channel can be filtered by category.
# Every post carries this shared tag plus category-specific tags defined next
# to each formatter (Telegram treats each whitespace-separated ``#word`` as a
# searchable tag).
TAG_COMMON = "#SpaceUpdates"


def hashtag_line(*tags: str) -> str:
    """Join hashtags into a single space-separated line, dropping blanks."""
    return " ".join(t for t in tags if t)


def coerce_json(value, default):
    """Return ``value`` decoded from JSON if it is a string.

    Sub-payloads arrive either already decoded or as the JSON text stored in
    the database. Returns ``default`` when decoding fails or the result is not
    of the same type as ``default`` (e.g. ``[]`` for a list, ``{}`` for a dict).
    """
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return default
    return value if isinstance(value, type(default)) else default


def fmt_utc(iso_str: str) -> str:
    """Format an ISO UTC timestamp (``Z`` or ``+00:00``) as ``dd.mm.yyyy HH:MM UTC``."""
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    return dt.strftime("%d.%m.%Y %H:%M UTC")
