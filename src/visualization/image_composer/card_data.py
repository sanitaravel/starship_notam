"""Turn a stored NOTAM or BNM row into the dict the card is drawn from."""

from __future__ import annotations

from datetime import datetime

from src.core.logging import logger
from src.parsers.coord_parser import (
    parse_coord_groups_from_text,
    parse_coords_from_text,
)
from src.parsers.notam_time import parse_notam_time
from src.parsers.schedule import _RU_MONTHS, parse_notam_windows_with_dates
from src.visualization.image_composer.titles import extract_starship_template


def notam_from_db_row(name: str, parsed: dict) -> dict:
    """Convert DB parsed dict into the simple notam dict used for rendering."""
    details = None
    # Prefer E field for human-readable text, then D, then join available fields
    if isinstance(parsed, dict):
        raw = parsed.get('E') or parsed.get('D') or '\n'.join(parsed.get(k, '') for k in ('A', 'B', 'C', 'D', 'E') if parsed.get(k))

        # Check for Starship-related NOTAMs and extract a more descriptive line if applicable
        selected_line = extract_starship_template(raw)

        if selected_line:
            details = selected_line
            logger.info("Selected detail line containing 'starship': %s", details)
        else:
            details = raw.replace('\n', ' ').strip()

        q = parsed.get('Q') if isinstance(parsed.get('Q'), dict) else None
        # Coordinates: always derive polygon/point from the E/D text (raw), not
        # from Q. First check for multiple AND-separated areas (e.g. a NOTAM
        # that defines two debris-response-area boundaries); when there are 2+
        # groups pass them through as a list-of-polygons so each is drawn
        # separately instead of being fused into one self-intersecting ring.
        radius_nm = None
        groups = parse_coord_groups_from_text(raw)
        if groups and len(groups) > 1:
            coords = [list(g) for g in groups]
            logger.info(
                "Parsed %d coordinate groups from E field/text (%s points)",
                len(groups), ", ".join(str(len(g)) for g in groups),
            )
        else:
            coords = parse_coords_from_text(raw)
        # extract zone code and upper limit (top height) if available
        zone_code = None
        top_limit = None
        if isinstance(coords, list) and coords and isinstance(coords[0], list):
            logger.info("Parsed %d coordinate groups from E field/text", len(coords))
        elif isinstance(coords, list) and coords:
            logger.info("Parsed %d coordinates from E field/text", len(coords))
        elif isinstance(coords, tuple) and coords:
            logger.info("Parsed center coordinate from E field/text")
        if q:
            logger.info("Q field: %s", q)
            zone_code = q.get('location') or q.get('qcode') or None
            top_limit = q.get('upper') or q.get('upper_limit') or None
            radius_nm = q.get('radius_nm')
    else:
        details = None
        coords = None
        radius_nm = None

    # Stored names use '_' in place of '/' (A0669_26 -> A0669/26).
    number = str(name).strip().replace('_', '/')

    # Strip trailing punctuation from details
    if details:
        import string
        trailing = set(string.punctuation) | {"…", "—", "–"}
        d = details.rstrip()
        while d and d[-1] in trailing:
            d = d[:-1].rstrip()
        details = d

    # Parse start/end times from common NOTAM fields if present
    start_raw = parsed.get('B') if isinstance(parsed, dict) else None
    if not start_raw:
        start_raw = parsed.get('start') if isinstance(parsed, dict) else None
    end_raw = parsed.get('C') if isinstance(parsed, dict) else None
    if not end_raw:
        end_raw = parsed.get('end') if isinstance(parsed, dict) else None

    start_dt = parse_notam_time(start_raw)
    end_dt = parse_notam_time(end_raw)
    start_str = start_dt.strftime('%d.%m.%Y, %H:%M UTC') if start_dt else None
    end_str = end_dt.strftime('%d.%m.%Y, %H:%M UTC') if end_dt else None

    # Active windows come from the D field (schedule), or - for NOTAMs that
    # keep their activation dates in the E-field prose (e.g. Starship DRA
    # notices with primary + backup dates) - from the E-field dates paired with
    # the D-field time window. The day-prefixed D formats only give a
    # day-of-month, so we anchor them to the start datetime (B) to recover the
    # correct month/year. When neither yields anything the list is empty and the
    # renderer falls back to the start/end display.
    schedule_raw = parsed.get('D') if isinstance(parsed, dict) else None
    e_raw = parsed.get('E') if isinstance(parsed, dict) else None
    windows = parse_notam_windows_with_dates(schedule_raw, e_raw, start_dt, end_dt)

    return {
        'number': number,
        'details': details or '',
        'coords': coords,
        'radius_nm': radius_nm,
        'meta': '(ДЛЯ ВОЗДУШНОГО ТРАНСПОРТА)',
        'author': '@sanitaravel',
        'start': start_str,
        'end': end_str,
        'windows': windows,
        # Q) derived fields
        'zone': zone_code,
        'top': top_limit,
    }


def _bnm_window_line(start: str, end: str) -> str | None:
    """ISO UTC window -> ``"Сентябрь 28, 12:15 - 14:14"``, the NOTAM card style."""
    try:
        s = datetime.fromisoformat(start.replace("Z", "+00:00"))
        e = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    return f"{_RU_MONTHS[s.month]} {s.day:02d}, {s:%H:%M} - {e:%H:%M}"


def bnm_card_data(notice: dict) -> dict:
    """Convert a stored BNM safety notice into the dict the card is drawn from.

    Each lettered hazard area is its own polygon group, so the map shows the
    high-risk and hazard areas separately.
    """
    flight = str(notice.get("flight") or "").strip()
    if flight:
        details = f"ОПАСНЫЕ ЗОНЫ ДЛЯ СУДОВ ПРИ ЗАПУСКЕ SPACEX STARSHIP FLT-{flight}"
    else:
        details = f"ОПАСНЫЕ ЗОНЫ ДЛЯ СУДОВ: {notice.get('mission') or 'КОСМИЧЕСКИЙ ЗАПУСК'}"

    groups = [
        [tuple(p) for p in area.get("coords") or []]
        for area in notice.get("areas") or []
    ]
    groups = [g for g in groups if g]

    windows = [
        line
        for w in notice.get("windows") or []
        if len(w) == 2 and (line := _bnm_window_line(*w))
    ]

    # "CGD-H BNM 0108-26": the district prefix goes on the meta line so the
    # number fits the left column at the title size.
    bnm_id = str(notice.get("bnm_id") or "")
    district, _, number = bnm_id.partition(" ")
    return {
        "title": "ОПОВЕЩЕНИЕ BNM",
        "number": number or bnm_id,
        "details": details,
        "coords": groups or None,
        "radius_nm": None,
        "meta": f"(ДЛЯ МОРСКОГО ТРАНСПОРТА) USCG {district}".rstrip(),
        "author": "@sanitaravel",
        "start": None,
        "end": None,
        "windows": windows,
        "zone": None,
        "top": None,
    }
