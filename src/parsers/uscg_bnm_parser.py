"""USCG Broadcast Notice to Mariners (BNM) parsing.

Pure-function parser for a Coast Guard GovDelivery RSS feed
(``https://public.govdelivery.com/topics/USDHSCG_414/feed.rss``). Each
``<item>`` is one bulletin; its ``description`` holds the full text as HTML::

    <title>SAFETY/TX - GULF OF AMERICA - CARIBBEAN SEA/SPACE OPERATIONS/CGD-H BNM 0108-26</title>
    <description>1. SPACE LAUNCH OPERATIONS, ... HAZARD AREAS FOR STARSHIP FLIGHT 14:
      A. HIGH RISK HAZARD AREA 25-12-00N 092-58-00W, ... AND 24-45-00N 092-43-00W.
      B. HAZARD AREA 25-58-00N 097-13-00W, ...
      2. PRIMARY AND BACKUP LAUNCH DAY HAZARD PERIODS INCLUDE:
      28/1215Z SEP 26 TO 28/1414Z SEP 26 ...
      CANCEL AT//050000Z OCT 26//</description>

The Southeast District writes vertices as ``FROM 25-58-00N/097-13-00W TO ...
TO BEGINNING`` (sometimes with a three-digit latitude, ``025-58-00N``) and its
windows without the ``Z``. A cancellation names the bulletin it cancels and,
for launches, the outcome::

    1. CANCEL CGD-SE BNM 9076-26 DTG 271742Z SEP 26 2. STARSHIP FLIGHT 14, SUCCESSFUL LAUNCH. BT

Only ``SPACE OPERATIONS`` bulletins are returned; the rest of the feed (aids
to navigation, Navy exercises, dredging) is dropped. All times are UTC.

It performs no network, database, or filesystem operations.

Public API:
    parse_uscg_bnm_feed(text: str) -> list[dict]
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from src.core.logging import logger

_SPACE_OPERATIONS = "SPACE OPERATIONS"

# "CGD-H BNM 0108-26", "CGD-SE BNM 9076-26"; before the 2025 renaming
# "CCGD8 BNM ..." and "CCGD-SE BNM ...".
_BNM_ID = re.compile(r"\b(C?CGD[-\w]*\s+BNM\s+\d{3,4}-\d{2})\b", re.IGNORECASE)

_CANCELS = re.compile(r"\bCANCEL\s+(C?CGD[-\w]*\s+BNM\s+\d{3,4}-\d{2})", re.IGNORECASE)

# The outcome follows the cancelled bulletin's DTG: "2. STARSHIP FLIGHT 14,
# SUCCESSFUL LAUNCH. BT".
_OUTCOME = re.compile(r"\b2\.\s+(.*?)\s*(?:\bBT\b|$)", re.DOTALL)

_FLIGHT = re.compile(r"\bSTARSHIP\s+FLIGHT\s+(\d+)", re.IGNORECASE)

_MISSION = re.compile(r"HAZARD AREAS FOR\s+([^:]+?)\s*:", re.IGNORECASE)

# Lettered hazard areas in paragraph 1: "A. HIGH RISK HAZARD AREA 25-12-00N ...".
_AREA = re.compile(r"(?:^|\s)([A-Z])\.\s+(.*?)(?=\s[A-Z]\.\s|$)", re.DOTALL)

# A vertex: "25-12-00N 092-58-00W" or "025-58-00N/097-13-00W"; seconds may be
# missing ("30-45N/80-56W") or fractional.
_VERTEX = re.compile(
    r"(\d{2,3})-(\d{2})(?:-(\d{2}(?:\.\d+)?))?([NS])[\s/,]*"
    r"(\d{2,3})-(\d{2})(?:-(\d{2}(?:\.\d+)?))?([EW])"
)

# "28/1215Z SEP 26 TO 28/1414Z SEP 26" (Heartland) or "28/1215 SEP 26 TO ..."
# (Southeast).
_WINDOW = re.compile(
    r"(\d{2})/(\d{4})Z?\s+([A-Z]{3})\s+(\d{2})\s+TO\s+"
    r"(\d{2})/(\d{4})Z?\s+([A-Z]{3})\s+(\d{2})",
    re.IGNORECASE,
)

_CANCEL_AT = re.compile(r"CANCEL AT//(\d{2})(\d{4})Z\s+([A-Z]{3})\s+(\d{2})//", re.IGNORECASE)

_MONTHS = {
    m: i
    for i, m in enumerate(
        ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"),
        start=1,
    )
}


def _plain_text(markup: str) -> str:
    """Bulletin HTML -> one line of upper-case text."""
    text = re.sub(r"<[^>]+>", " ", markup or "")
    return " ".join(html.unescape(text).split()).upper()


def _iso(day: str, hhmm: str, month: str, yy: str) -> str:
    """``("28", "1215", "SEP", "26")`` -> ``"2026-09-28T12:15:00Z"``; ``""`` if invalid."""
    try:
        dt = datetime(
            2000 + int(yy), _MONTHS[month.upper()], int(day),
            int(hhmm[:2]), int(hhmm[2:]), tzinfo=timezone.utc,
        )
    except (KeyError, ValueError):
        return ""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _degrees(deg: str, minutes: str, seconds: str | None, hemisphere: str) -> float:
    value = int(deg) + int(minutes) / 60 + float(seconds or 0) / 3600
    return round(-value if hemisphere in "SW" else value, 6)


def _areas(text: str) -> list[dict]:
    """Paragraph 1's lettered areas -> ``[{"label": ..., "coords": [[lat, lon], ...]}]``."""
    start = _MISSION.search(text)
    if not start:
        return []
    end = re.search(r"\s2\.\s", text[start.end():])
    section = text[start.end(): start.end() + end.start() if end else len(text)]

    areas = []
    for _, body in _AREA.findall(section):
        vertices = list(_VERTEX.finditer(body))
        if not vertices:
            continue
        label = body[: vertices[0].start()].strip()
        label = re.sub(r"\bFROM$", "", label).strip(" :,")
        coords = [
            [_degrees(*v.group(1, 2, 3, 4)), _degrees(*v.group(5, 6, 7, 8))]
            for v in vertices
        ]
        areas.append({"label": label, "coords": coords})
    return areas


def _published(value: str) -> str:
    """RFC 822 ``pubDate`` -> ISO UTC (``2026-09-25T18:24:01Z``); ``""`` if invalid."""
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_item(item: ET.Element) -> dict | None:
    title = " ".join((item.findtext("title") or "").split())
    if _SPACE_OPERATIONS not in title.upper():
        return None
    bnm = _BNM_ID.search(title)
    if not bnm:
        logger.info("Skipping USCG bulletin without a BNM number: %s", title)
        return None
    bnm_id = " ".join(bnm.group(1).upper().split())

    parts = [p.strip() for p in title.split("/")]
    kind = parts[0].upper()
    # Between the kind and the "SPACE OPERATIONS/<id>" tail.
    region = "/".join(parts[1:-2]) if len(parts) > 3 else ""

    text = _plain_text(item.findtext("description") or "")
    flight = _FLIGHT.search(text)
    mission = _MISSION.search(text)
    cancel_at = _CANCEL_AT.search(text)
    record = {
        "notice_key": f"{kind} {bnm_id}",
        "bnm_id": bnm_id,
        "kind": kind,
        "region": region,
        "title": title,
        "flight": flight.group(1) if flight else "",
        "mission": " ".join(mission.group(1).split()) if mission else "",
        "starship": "STARSHIP" in text,
        "areas": _areas(text),
        "windows": [
            [_iso(*w[:4]), _iso(*w[4:])]
            for w in _WINDOW.findall(text)
            if _iso(*w[:4]) and _iso(*w[4:])
        ],
        "cancel_at": _iso(*cancel_at.groups()) if cancel_at else "",
        "cancels": "",
        "outcome": "",
        "published_at": _published(item.findtext("pubDate") or ""),
        "link": (item.findtext("link") or "").strip(),
    }
    cancels = _CANCELS.search(text)
    if cancels:
        record["cancels"] = " ".join(cancels.group(1).split())
        outcome = _OUTCOME.search(text, cancels.end())
        if outcome:
            record["outcome"] = outcome.group(1).strip(" .")
    return record


def parse_uscg_bnm_feed(text: str) -> list[dict]:
    """Return the ``SPACE OPERATIONS`` bulletins of a GovDelivery RSS feed.

    Returns
    -------
    list[dict]
        One record per bulletin, in feed order (newest first), with the keys
        ``notice_key`` (``"SAFETY CGD-H BNM 0108-26"``: kind plus BNM number,
        since a cancellation reuses the number of the bulletin it cancels),
        ``bnm_id``, ``kind`` (``SAFETY``, ``CANCELLATION``, ...), ``region``,
        ``title``, ``flight`` (Starship flight number or ``""``), ``mission``
        (``"STARSHIP FLIGHT 14"``, ``"CRS-35"``), ``starship`` (the text
        mentions Starship), ``areas`` (``[{"label", "coords": [[lat, lon],
        ...]}]``), ``windows`` (``[[start, end], ...]`` as ISO UTC),
        ``cancel_at``, ``cancels`` (the BNM number a cancellation cancels),
        ``outcome`` (``"STARSHIP FLIGHT 14, SUCCESSFUL LAUNCH"``),
        ``published_at`` and ``link``. Junk input yields ``[]``.
    """
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        logger.error("USCG BNM feed is not valid XML")
        return []
    records = []
    for item in root.iter("item"):
        record = _parse_item(item)
        if record:
            records.append(record)
    return records
