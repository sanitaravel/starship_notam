"""Parse NOTAM B)/C) times.

One parser shared by the NOTAM parser (which stores B/C as ISO strings), the
image composer and the Telegram caption builder (which display them).
"""

import re
from datetime import datetime, timezone
from typing import Optional

# Characters that can be part of a time; everything else (e.g. the "EST" in
# "2607160500EST") is dropped before looking for compact digit tokens.
_NOISE_RE = re.compile(r'(?i)[^0-9TZ:\-\s]')
_COMPACT_RE = re.compile(r'\d{12}|\d{10}')

# Tried in order after compact tokens and ISO-8601.
_FORMATS = (
    '%Y%m%dT%H%M', '%y%m%dT%H%M',
    '%d.%m.%Y %H:%M', '%d.%m.%Y %H:%M:%S', '%d.%m.%Y',
    '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M',
    '%d %b %Y %H:%M', '%d %b %Y', '%d %B %Y %H:%M', '%d %B %Y',
    '%Y%m%d',
)


def parse_notam_time(raw) -> Optional[datetime]:
    """Parse a NOTAM time into a naive UTC ``datetime``, or None.

    Accepts, in order of preference:

    - a ``datetime`` (an aware one is converted to UTC);
    - a compact ``YYYYMMDDhhmm`` or ``YYMMDDhhmm`` token anywhere in the text,
      as in raw NOTAM fields (``2607160500``, ``2607160500EST``);
    - ISO-8601, with ``T`` or a space, optional seconds and ``Z``/offset (the
      form the NOTAM parser stores);
    - a few other formats listed in ``_FORMATS``.

    Returns None for anything else (e.g. ``PERM``).
    """
    if raw is None or raw == '':
        return None
    if isinstance(raw, datetime):
        dt = raw
    else:
        dt = _parse_text(str(raw).strip())
        if dt is None:
            return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _parse_text(s: str) -> Optional[datetime]:
    cleaned = _NOISE_RE.sub('', s)
    for token in _COMPACT_RE.findall(cleaned):
        try:
            return datetime.strptime(token, '%Y%m%d%H%M' if len(token) == 12 else '%y%m%d%H%M')
        except ValueError:
            continue

    iso = s[:-1] + '+00:00' if s.endswith('Z') else s
    try:
        return datetime.fromisoformat(iso)
    except ValueError:
        pass

    for candidate in dict.fromkeys((s, cleaned.strip())):
        for fmt in _FORMATS:
            try:
                return datetime.strptime(candidate, fmt)
            except ValueError:
                continue
    return None
