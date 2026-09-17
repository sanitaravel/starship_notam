"""PIL-based NOTAM image composition.

This module composes the final NOTAM image: it lays out the canvas, loads the
project fonts, renders the descriptive text (title, number, details, times,
zone/height), and pastes the map tile produced by
:func:`starship_notam.visualization.map_renderer.render_map`.

Coordinate extraction is delegated to
:func:`starship_notam.parsers.coord_parser.parse_coords_from_text` (the
visualization layer contains no coordinate-parsing logic of its own).

Heavy image dependencies (Pillow) are imported lazily inside the function
bodies so that importing this module does not require Pillow to be installed
and keeps the visualization layer independently importable.

Public entry points:
    render_notam_image(notam_dict, output_path) -> str
    plot_single_notam(name, parsed, coords, out_path, _unused=None) -> str
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from starship_notam.core.logging import logger
from starship_notam.parsers.coord_parser import parse_coords_from_text
from starship_notam.visualization.map_renderer import MAP_H, MAP_W, render_map

# Canvas and layout constants
CANVAS_W = 1316
CANVAS_H = 711
PADDING = 24

# Left width constraint
LEFT_MAX_W = 444

# Colors
# Background color #262626 (38,38,38)
BG_COLOR = (38, 38, 38)
WHITE = (254, 254, 254)
GRAY_AAA = (170, 170, 170)
RED_CF = (207, 0, 0)

# Fonts directory lives at the project root, two levels up from this file:
#   starship_notam/visualization/image_composer.py -> starship_notam/ -> project root
_FONTS_DIR = Path(__file__).resolve().parents[2] / "fonts"


def load_font(name: str, size: int, weight: str | None = None):
    """Load a TrueType font, preferring the project's ``fonts/`` directory.

    Falls back to common system font locations and finally to PIL's default
    font if nothing suitable can be loaded.
    """
    from PIL import ImageFont

    project_fonts = _FONTS_DIR
    candidates = []

    # Exact file in project fonts
    if project_fonts.exists():
        exact = project_fonts / name
        candidates.append(str(exact))
        # Look for files that mention JetBrains or the base name
        for f in project_fonts.glob("*.ttf"):
            fn = f.name.lower()
            if name.lower() in fn or "jetbrains" in fn:
                candidates.append(str(f))

    # System font locations
    import os

    candidates.extend([
        os.path.join("/usr/share/fonts", name),
        os.path.join("/Library/Fonts", name),
        os.path.join(str(Path.home()), ".fonts", name),
        name,
    ])

    seen = set()
    for c in candidates:
        if not c or c in seen:
            continue
        seen.add(c)
        try:
            logger.debug("Trying font candidate: %s", c)
            return ImageFont.truetype(c, size)
        except Exception:
            continue

    logger.warning("Falling back to default PIL font for size %s", size)
    return ImageFont.load_default()


def _parse_notam_time(raw):
    """Parse various NOTAM time formats into a datetime (UTC) or None."""
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw
    s = str(raw).strip()

    # ISO with trailing Z
    try:
        if s.endswith('Z') and 'T' in s:
            s2 = s[:-1] + '+00:00'
            dt = datetime.fromisoformat(s2)
            return dt
    except Exception:
        pass

    # Look for compact numeric tokens like YYYYMMDDHHMM, YYMMDDHHMM or YYYYMMDD
    m = re.search(r'(\d{12}|\d{10}|\d{8})', s)
    if m:
        tok = m.group(1)
        try:
            if len(tok) == 12:
                return datetime.strptime(tok, '%Y%m%d%H%M').replace(tzinfo=timezone.utc)
            if len(tok) == 10:
                dt = datetime.strptime(tok, '%y%m%d%H%M')
                if dt.year < 100:
                    dt = dt.replace(year=dt.year + 2000)
                return dt.replace(tzinfo=timezone.utc)
            if len(tok) == 8:
                if tok.startswith('20') or tok.startswith('19'):
                    return datetime.strptime(tok, '%Y%m%d').replace(tzinfo=timezone.utc)
                dt = datetime.strptime(tok, '%y%m%d')
                if dt.year < 100:
                    dt = dt.replace(year=dt.year + 2000)
                return dt.replace(tzinfo=timezone.utc)
        except Exception:
            pass

    # Try common ISO / human formats
    try:
        dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
        return dt
    except Exception:
        pass

    patterns = [
        '%d.%m.%Y %H:%M', '%d.%m.%Y %H:%M:%S', '%d.%m.%Y',
        '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M',
        '%d %b %Y %H:%M', '%d %b %Y', '%d %B %Y %H:%M', '%d %B %Y'
    ]
    for fmt in patterns:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except Exception:
            pass

    return None


# Russian month abbreviations for compact date labels (index 1..12).
_RU_MONTHS = [
    "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]


def _fmt_hhmm(tok: str) -> str | None:
    """Format a 4-digit ``HHMM`` token as ``HH:MM``; return None if invalid."""
    tok = tok.strip()
    if not re.fullmatch(r"\d{4}", tok):
        return None
    hh, mm = tok[:2], tok[2:]
    try:
        if int(hh) > 24 or int(mm) > 59:
            return None
    except ValueError:
        return None
    return f"{hh}:{mm}"


def _fmt_window(start_tok: str, end_tok: str) -> str | None:
    """Format a ``HHMM``-``HHMM`` pair as ``HH:MM - HH:MM``."""
    a = _fmt_hhmm(start_tok)
    b = _fmt_hhmm(end_tok)
    if a is None or b is None:
        return None
    return f"{a} - {b}"


def _day_label(day: int, base: datetime | None) -> str:
    """Return a ``Месяц DD`` label for a day-of-month using ``base`` month.

    ``base`` (the NOTAM start datetime) supplies the month/year. When the day
    number is smaller than the base day the window rolls into the next month.
    """
    if base is None:
        return f"{day:02d}"
    month = base.month
    if day < base.day:
        month += 1
        if month > 12:
            month = 1
    return f"{_RU_MONTHS[month]} {day:02d}"


def parse_notam_windows(raw, base: datetime | None = None) -> list[str]:
    """Parse the NOTAM schedule (DB column ``D``) into display window strings.

    Returns a list of human-readable Russian lines describing each active
    window. Supported input shapes (case-insensitive), based on real feed data:

    * ``DLY 0800-2059`` / ``DAILY 2334-0300`` / ``DAILY 2200 - 0056``
      -> ``Ежедневно 08:00 - 20:59``
    * ``2045/0100 DLY`` -> ``Ежедневно 20:45 - 01:00``
    * ``28 1223-1447`` (one per line) -> ``Сентябрь 28, 12:23 - 14:47``
    * ``20 0334-0812, 21 0320-0758`` (comma separated, may wrap)
    * ``23-28 BTN 0000-0108 2107-2359`` (day range expands to one line per day,
      each with both windows)
    * ``2245-0241`` (bare window, whole period) -> ``22:45 - 02:41``

    Returns an empty list when nothing parseable is found (caller falls back
    to the B/C start/end display).
    """
    if not raw:
        return []
    text = str(raw).strip()
    if not text:
        return []

    daily = bool(re.search(r"\b(DLY|DAILY)\b", text, re.IGNORECASE))

    # ``entries`` is an ordered list of (kind, key, windows) tuples where:
    #   * kind "day"   -> key is an int day-of-month
    #   * kind "range" -> key is a (d1, d2) tuple of day-of-month
    #   * kind "plain" -> key is None (DLY / bare window with no day)
    # and ``windows`` is a list of formatted "HH:MM–HH:MM" strings for that key.
    entries: list[tuple[str, object, list[str]]] = []

    # Split into segments on newlines and commas; each segment describes one
    # day / day-range and its window(s).
    segments = [seg.strip() for seg in re.split(r"[\n,]+", text) if seg.strip()]

    for seg in segments:
        # Strip DLY/DAILY tokens; they only signal recurrence, handled below.
        seg_clean = re.sub(r"\b(DLY|DAILY)\b", " ", seg, flags=re.IGNORECASE).strip()

        # Day range: "23-28 BTN <windows>". A day is 1-2 digits; the windows
        # that follow are 4-digit HHMM tokens, so we require the day tokens to
        # be followed by whitespace before the schedule body. BTN ("between")
        # is an optional separator.
        m_range = re.match(
            r"^(\d{1,2})\s*-\s*(\d{1,2})\s+(?:BTN\s+)?(\d{4}.*)$",
            seg_clean, re.IGNORECASE,
        )
        # Single day prefix: "28 1223-1447". The day is 1-2 digits followed by
        # whitespace and then a 4-digit time. Requiring the trailing \d{4}
        # prevents a bare time token (e.g. "2245-0241") from being read as a
        # day number.
        m_day = re.match(
            r"^(\d{1,2})\s+(?:BTN\s+)?(\d{4}.*)$",
            seg_clean, re.IGNORECASE,
        )

        if m_range and 1 <= int(m_range.group(1)) <= 31 and 1 <= int(m_range.group(2)) <= 31:
            d1, d2, rest = int(m_range.group(1)), int(m_range.group(2)), m_range.group(3)
            entries.append(("range", (d1, d2), _windows_in(rest)))
            continue
        if m_day and 1 <= int(m_day.group(1)) <= 31:
            day, rest = int(m_day.group(1)), m_day.group(2)
            entries.append(("day", day, _windows_in(rest)))
            continue

        # No day prefix: either "DLY HHMM-HHMM"/"HHMM/HHMM" or a bare window.
        # Support slash separator (e.g. "2045/0100").
        rest = seg_clean.replace("/", "-")
        entries.append(("plain", None, _windows_in(rest)))

    return _format_entries(entries, base, daily)


def _windows_in(rest: str) -> list[str]:
    """Extract all ``HHMM-HHMM`` pairs in ``rest`` as ``HH:MM–HH:MM`` strings."""
    out: list[str] = []
    for start_tok, end_tok in re.findall(r"(\d{4})\s*-\s*(\d{4})", rest):
        win = _fmt_window(start_tok, end_tok)
        if win is not None:
            out.append(win)
    return out


def _format_entries(entries, base: datetime | None, daily: bool) -> list[str]:
    """Turn parsed schedule entries into display lines.

    Each entry produces one line per window in the form
    ``Месяц DD, HH:MM - HH:MM`` (e.g. ``Сентябрь 28, 12:23 - 14:47``). Every
    day is listed on its own line; consecutive identical days are NOT collapsed
    into ranges. Day-range entries (``DD-DD``) are expanded to a line per day.
    """
    lines: list[str] = []
    for kind, key, wins in entries:
        if not wins:
            continue

        if kind == "day":
            label = _day_label(key, base)
            for w in wins:
                lines.append(f"{label}, {w}")
        elif kind == "range":
            d1, d2 = key
            for day in _expand_day_range(d1, d2):
                label = _day_label(day, base)
                for w in wins:
                    lines.append(f"{label}, {w}")
        else:  # plain
            prefix = "Ежедневно " if daily else ""
            for w in wins:
                lines.append(f"{prefix}{w}")

    # De-duplicate while preserving order.
    seen = set()
    unique: list[str] = []
    for w in lines:
        if w not in seen:
            seen.add(w)
            unique.append(w)
    return unique


def _expand_day_range(d1: int, d2: int) -> list[int]:
    """Expand a ``DD-DD`` day range into individual day numbers.

    Handles a range that wraps across a month boundary (e.g. 30-02) by
    continuing to count up until the end day is reached again.
    """
    if d1 <= d2:
        return list(range(d1, d2 + 1))
    # Wraps into the next month: 30, 31, then 01..d2. We don't know the source
    # month length here, so include 31 as an upper bound; _day_label rolls the
    # month over for days smaller than the base day.
    return list(range(d1, 32)) + list(range(1, d2 + 1))


def extract_starship_template(notam: str) -> str | None:
    """Return a descriptive Russian-language line for Starship-related NOTAMs.

    Returns None when the NOTAM text does not match a known Starship template.
    """
    if not notam:
        return None
    text = " ".join(notam.upper().split())

    # 0. TFR ground/surface hazard area wording
    if any(keyword in text for keyword in [
        "SURFACE HAZARD OPERATIONS WI AN AREA DEFINED",
        "SURFACE HAZARD WI AN AREA DEFINED",
        "GROUND HAZARD WI AN AREA DEFINED",
    ]):
        return "GROUND HAZARD AREA"

    # 0b. High energy testing TFR (SpaceX Starship-related, no flight number)
    if "HIGH ENERGY TESTING" in text and "SPACEX" in text:
        return "ВЫСОКОЭНЕРГЕТИЧЕСКИЕ ТЕСТИРОВАНИЯ"

    # ----------------------------
    # Extract flight number
    # ----------------------------
    # Run flight extraction BEFORE the flight-free branches (0c) so a NOTAM that
    # carries a recognizable Starship flight number gets the specific, flight-
    # referencing template rather than the generic flight-free summary. Real
    # NOTAM feeds contain OCR/transcription quirks, so the patterns tolerate:
    #   * "SPACE X STARSHIP" (space inside "SPACEX")
    #   * "FTL-14" (transposed letters for the intended "FLT-14")
    flight = None

    patterns = [
        # Accept FLT and the transposed-typo FTL, with optional separators, and
        # the "SPACE X" spacing variant before STARSHIP.
        r"STARSHIP\s+F(?:LT|TL)[- ]?(\d+)",
        r"STARSHIP\s+FLIGHT[- ]?(\d+)",
        r"SPACE\s?X\s+STARSHIP\s+F(?:LT|TL)[- ]?(\d+)",
        r"SPACE\s?X\s+STARSHIP\s+FLIGHT[- ]?(\d+)",
    ]

    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            flight = m.group(1)
            break

    # 0c. Space vehicle re-entry / splashdown with NO recognizable flight number
    # (e.g. "RE-ENTRY OF SPACE VEHICLE OVER PACIFIC OCEAN WITH SPLASHDOWN").
    # Only fires when flight extraction above found nothing, so flighted
    # re-entry NOTAMs fall through to the flight-carrying template (branch 2).
    if flight is None and "RE-ENTRY" in text and (
        "SPACE VEHICLE" in text
        or "PACIFIC OCEAN" in text
        or "SPLASHDOWN" in text
    ):
        return (
            "ЗОНА ВХОДА В АТМОСФЕРУ И ПРИВОДНЕНИЯ"
        )

    if not flight:
        return None

    # ----------------------------
    # Classification
    # ----------------------------

    # 1. Airspace closure during ascent
    if any(keyword in text for keyword in [
        "ASCENT",
        "ALT RESERVATION",
        "AIRSPACE DCC",
        "STNR ALT RESERVATION"
    ]):
        return (
            f"ЗАКРЫТИЕ ВОЗДУШНЕГО ПРОСТРАНСТВА "
            f"В СВЯЗИ С ЗАПУСКОМ SPACEX STARSHIP "
            f"FLT-{flight}"
        )

    # 2. Reentry + splashdown
    if (
        ("REENTRY" in text or "RE-ENTRY" in text)
        and "SPLASHDOWN" in text
    ):
        return (
            f"ЗОНА ВХОДА В АТМОСФЕРУ И ПРИВОДНЕНИЯ  "
            f"SPACEX STARSHIP FLT-{flight}"
        )

    # 3. Reentry only
    if any(keyword in text for keyword in [
        "REENTRY OF ROCKET",
        "RE-ENTRY",
        "FOR REENTRY",
        "REENTRY"
    ]):
        return (
            f"ЗОНА ВХОДА В АТМОСФЕРУ "
            f"КОСМИЧЕСКОГО КОРАБЛЯ SPACEX STARSHIP "
            f"FLT-{flight}"
        )

    # 4. Debris / launch hazard
    if any(keyword in text for keyword in [
        "DANGEROUS AREA",
        "DEBRIS RESPONSE AREA",
        "DEBRIS RESPONSE AREAS", "HAZARDOUS OPERATION",
        "FALLING DEBRIS",
        "POSSIBILITY OF FALLING DEBRIS",
        "ACFT HAZARD AREA",
        "DUE LAUNCH OF SPACEX STARSHIP",
        "DUE TO THE LAUNCH OF THE",
        "TEMPORARY DANGER AREAS",
        "TEMPORARY DANGER AREA",
        "SPACE DEBRIS",
        "DEBRIS RETURN",
        "SPACE DEBRIS RETURN",
    ]):
        return (
            f"ВОЗМОЖНОЕ ПАДЕНИЕ ОБЛОМКОВ "
            f"В РЕЗУЛЬТАТЕ ЗАПУСКА SPACEX STARSHIP "
            f"FLT-{flight}"
        )

    # 5. Ascent
    if any(keyword in text for keyword in [
        "STARSHIP ASCENT",
        "SPACEX STARSHIP ASCENT"
    ]):
        return (
            f"ЗОНА ЗАПУСКА SPACEX STARSHIP "
            f"FLT-{flight}"
        )

    # 6. Generic fallback for recognized Starship flights.
    # A flight number was extracted but no specific branch matched. Return a
    # concise flight-referencing summary line instead of None so the card shows
    # a shortened line rather than the full raw NOTAM text. Non-Starship text
    # never reaches here (it returns None earlier when no flight is found).
    return f"ЗОНА NOTAM SPACEX STARSHIP FLT-{flight}"


def _notam_from_db_row(name: str, parsed: dict) -> dict:
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
        # Coordinates: always derive polygon/point from the E/D text (raw), not from Q
        coords = parse_coords_from_text(raw)
        radius_nm = None
        # extract zone code and upper limit (top height) if available
        zone_code = None
        top_limit = None
        if isinstance(coords, list) and coords:
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

    # Normalize number: strip trailing .json (if present), then replace
    # underscore with slash (A0669_26 -> A0669/26). This guards against
    # legacy or malformed names like 'E1777_26.json' that would otherwise
    # become 'E1777/26.json' when only replacing underscores.
    number = name
    try:
        if isinstance(name, str):
            raw_name = name.strip()
            if raw_name.lower().endswith('.json'):
                raw_name = raw_name[:-5]
            number = raw_name.replace('_', '/')
    except Exception:
        number = name

    if number != name:
        logger.info("Normalized NOTAM name '%s' -> '%s'", name, number)

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

    start_dt = _parse_notam_time(start_raw)
    end_dt = _parse_notam_time(end_raw)
    start_str = start_dt.strftime('%d.%m.%Y, %H:%M UTC') if start_dt else None
    end_str = end_dt.strftime('%d.%m.%Y, %H:%M UTC') if end_dt else None

    # Active windows come from the D field (schedule). The day-prefixed formats
    # only give a day-of-month, so we anchor them to the start datetime (B) to
    # recover the correct month/year. When D is empty/unparseable, the list is
    # empty and the renderer falls back to the start/end display.
    schedule_raw = parsed.get('D') if isinstance(parsed, dict) else None
    windows = parse_notam_windows(schedule_raw, start_dt)

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


def render_notam_image(notam_dict: dict, output_path: str = "notam_sample.png") -> str:
    """Compose the final NOTAM image (canvas + text + map) and save it.

    Coordinates present in ``notam_dict['coords']`` are used directly. If they
    are missing/unparseable the map renderer falls back to a default global
    map extent.

    Returns the ``output_path`` the image was saved to.
    """
    from PIL import Image, ImageDraw

    notam = notam_dict
    logger.info("Rendering NOTAM image for %s", notam.get("number"))
    img = Image.new("RGBA", (CANVAS_W, CANVAS_H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Layout: right map box positioned with PADDING from right and top
    map_x = CANVAS_W - PADDING - MAP_W
    map_y = PADDING

    # Left column area
    left_x = PADDING
    left_y = PADDING
    left_w = min(LEFT_MAX_W, map_x - PADDING - left_x)

    # Load fonts
    title_font = load_font("JetBrainsMono-Bold.ttf", 48)
    number_font = load_font("JetBrainsMono-Bold.ttf", 48)
    details_font = load_font("JetBrainsMono-Regular.ttf", 28)
    small_font = load_font("JetBrainsMono-Regular.ttf", 16)
    caption_font = load_font("JetBrainsMono-Regular.ttf", 14)

    # Draw texts with specified styles
    # Title: ОПОВЕЩЕНИЕ NOTAM
    draw.text((left_x, left_y), "ОПОВЕЩЕНИЕ NOTAM", font=title_font, fill=WHITE)
    left_y += 48 + 4

    # Meta line (ДЛЯ ВОЗДУШНОГО ТРАНСПОРТА)
    draw.text((left_x, left_y), notam.get("meta", "(ДЛЯ ВОЗДУШНОГО ТРАНСПОРТА)"), font=small_font, fill=WHITE)
    left_y += 16 + 4

    # Author
    draw.text((left_x, left_y), notam.get("author", "@sanitaravel"), font=caption_font, fill=GRAY_AAA)
    left_y += 14 + 16

    # NOTAM number
    draw.text((left_x, left_y), notam.get("number", ""), font=number_font, fill=RED_CF)
    left_y += 48 + 20

    # Details (wrap to LEFT_MAX_W)
    details = notam.get("details", "")
    # Simple wrapping
    lines = []
    words = details.split()
    cur = ""
    for w in words:
        test = (cur + " " + w).strip()
        w_box = draw.textbbox((0, 0), test, font=details_font)
        if w_box[2] - w_box[0] > left_w:
            if cur:
                lines.append(cur)
            cur = w
        else:
            cur = test
    if cur:
        lines.append(cur)

    for ln in lines:
        draw.text((left_x, left_y), ln, font=details_font, fill=WHITE)
        left_y += 28 + 4

    left_y += 12

    # Active windows (from the D schedule field). Render a "Действует:" header
    # followed by one line per active window. When no windows were parsed
    # (D field empty/unparseable) fall back to the classic Начало/Завершение
    # start/end display so those NOTAMs still show timing information.
    time_label_font = load_font("JetBrainsMono-Bold.ttf", 24)
    time_value_font = load_font("JetBrainsMono-Regular.ttf", 24)
    time_label_color = WHITE
    time_value_color = (255, 128, 20)  # #FF8014
    time_gap = 8

    windows = notam.get('windows') or []

    if windows:
        left_y += 4
        draw.text((left_x, left_y), "Действует (UTC):", font=time_label_font, fill=time_label_color)
        left_y += 24 + 6
        for win in windows:
            draw.text((left_x, left_y), win, font=time_value_font, fill=time_value_color)
            left_y += 24 + 2
    else:
        # Fallback: right-align the start/end values against the column right
        # edge; if space is insufficient, left-align them after the widest label.
        start_str = notam.get('start')
        end_str = notam.get('end')

        rows = []
        if start_str:
            lb_box = draw.textbbox((0, 0), "Начало:", font=time_label_font)
            vb_box = draw.textbbox((0, 0), start_str, font=time_value_font)
            rows.append(("Начало:", start_str, lb_box[2] - lb_box[0], vb_box[2] - vb_box[0]))
        if end_str:
            lb_box = draw.textbbox((0, 0), "Завершение:", font=time_label_font)
            vb_box = draw.textbbox((0, 0), end_str, font=time_value_font)
            rows.append(("Завершение:", end_str, lb_box[2] - lb_box[0], vb_box[2] - vb_box[0]))

        if rows:
            left_y += 6
            max_lb_w = max(r[2] for r in rows)
            max_vb_w = max(r[3] for r in rows)
            # space after widest label
            min_value_left = left_x + max_lb_w + time_gap
            # candidate left for a right-aligned column that fits the largest value
            candidate_value_left = left_x + left_w - max_vb_w

            if candidate_value_left >= min_value_left:
                # We can right-align values to the column right edge (left_x + left_w)
                for label, value, lb_w, vb_w in rows:
                    draw.text((left_x, left_y), label, font=time_label_font, fill=time_label_color)
                    # right-align each value so their right edges match left_x + left_w
                    value_x = left_x + left_w - vb_w
                    draw.text((value_x, left_y), value, font=time_value_font, fill=time_value_color)
                    left_y += 24 + 6
            else:
                # Not enough space — put values in a consistent column after widest label
                value_left = min_value_left
                for label, value, lb_w, vb_w in rows:
                    draw.text((left_x, left_y), label, font=time_label_font, fill=time_label_color)
                    draw.text((value_left, left_y), value, font=time_value_font, fill=time_value_color)
                    left_y += 24 + 6

    left_y += 12

    # Zone and top height display (under the time block)
    zone = notam.get('zone')
    top = notam.get('top')
    if zone or top:
        # Determine height text, treating 999 as unlimited
        height_text = None
        if top is not None:
            try:
                top_int = int(str(top).lstrip('0') or '0')
            except Exception:
                top_int = None
            if top_int == 999:
                height_text = 'Неограниченно'
            else:
                height_text = str(top)

        parts = []
        if zone:
            parts.append(f"Зона: {zone}")
        if height_text:
            parts.append(f"Высота: {height_text}")
        if parts:
            zone_line = ", ".join(parts)
            left_y += 6
            # Use JetBrains Mono regular at 24px (time_value_font) and white color
            draw.text((left_x, left_y), zone_line, font=time_value_font, fill=WHITE)
            left_y += 24 + 6

    # Draw right map placeholder (rounded rectangle)
    map_box = (map_x, map_y, map_x + MAP_W, map_y + MAP_H)
    # Background for map — match canvas background to avoid visible seams
    draw.rectangle(map_box, fill=BG_COLOR)
    # Coordinates and radius for map rendering
    coords = notam.get("coords")
    radius_nm = notam.get("radius_nm")

    # Try rendering a proper Earth map with the polygon/point using Cartopy
    try:
        map_img = render_map(coords, (MAP_W, MAP_H), radius_nm=radius_nm)
        img.paste(map_img, (map_x, map_y), map_img)
    except Exception:
        logger.exception("Cartopy map rendering failed, falling back to PIL rendering")
        # Fallback: draw plain map background (match canvas background to avoid seams)
        draw.rectangle(map_box, fill=BG_COLOR)
        try:
            if isinstance(coords, list) and coords:
                lats = [p[0] for p in coords]
                lons = [p[1] for p in coords]
                min_lat, max_lat = min(lats), max(lats)
                min_lon, max_lon = min(lons), max(lons)
                pad = 16
                avail_w = MAP_W - pad * 2
                avail_h = MAP_H - pad * 2
                lat_span = max_lat - min_lat or 1e-6
                lon_span = max_lon - min_lon or 1e-6
                scale = min(avail_w / lon_span, avail_h / lat_span)
                center_lat = (max_lat + min_lat) / 2.0
                center_lon = (max_lon + min_lon) / 2.0
                pts = []
                for lat, lon in coords:
                    x = int(map_x + pad + avail_w / 2.0 + (lon - center_lon) * scale)
                    y = int(map_y + pad + avail_h / 2.0 - (lat - center_lat) * scale)
                    pts.append((x, y))
                overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
                od = ImageDraw.Draw(overlay)
                od.polygon(pts, fill=(207, 0, 0, 80), outline=(255, 80, 80, 200))
                img = Image.alpha_composite(img, overlay)
                draw = ImageDraw.Draw(img)
            elif isinstance(coords, tuple) and coords:
                lat, lon = coords
                r = None
                try:
                    if radius_nm is not None:
                        r = float(str(radius_nm).strip())
                        if r <= 0:
                            r = None
                except Exception:
                    r = None
                if r is not None:
                    import math
                    # Render a simple circle in fallback mode around center.
                    lat_span = max((r / 60.0) * 4.0, 0.3)
                    lon_span = max((r / (60.0 * max(math.cos(math.radians(lat)), 1e-6))) * 4.0, 0.3)
                    min_lat, max_lat = lat - lat_span / 2.0, lat + lat_span / 2.0
                    min_lon, max_lon = lon - lon_span / 2.0, lon + lon_span / 2.0
                    pad = 16
                    avail_w = MAP_W - pad * 2
                    avail_h = MAP_H - pad * 2
                    scale = min(avail_w / max(max_lon - min_lon, 1e-6), avail_h / max(max_lat - min_lat, 1e-6))
                    cx = int(map_x + pad + avail_w / 2.0)
                    cy = int(map_y + pad + avail_h / 2.0)
                    rx = max(1, int((r / (60.0 * max(math.cos(math.radians(lat)), 1e-6))) * scale))
                    ry = max(1, int((r / 60.0) * scale))
                    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
                    od = ImageDraw.Draw(overlay)
                    od.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=(207, 0, 0, 80), outline=(255, 80, 80, 200), width=2)
                    img = Image.alpha_composite(img, overlay)
                    draw = ImageDraw.Draw(img)
            # If coords is a single tuple and no radius is available, don't draw marker per request
        except Exception:
            logger.exception("Fallback drawing failed")

    # Draw a uniform 2px frame around the map. The cartopy axes spine renders
    # unevenly (the right/top edges get clipped at the figure boundary), so we
    # draw our own border here to guarantee all four sides match. Re-create the
    # drawing context because the fallback path may have replaced ``img`` via
    # alpha compositing.
    draw = ImageDraw.Draw(img)
    draw.rectangle(map_box, outline=(58, 58, 58), width=2)

    img.save(output_path)
    logger.info("Saved NOTAM image to %s", output_path)
    return output_path


def plot_single_notam(name: str, parsed: dict, coords, out_path: str, _unused=None) -> str:
    """Blocking helper used by external callers to generate a NOTAM image.

    This function is suitable for running in a thread (e.g. via
    ``asyncio.to_thread``) and simply wraps existing helpers to produce
    the file at ``out_path`` and return that path.
    """
    try:
        # Prefer converting the DB row into the renderer's expected dict.
        try:
            notam = _notam_from_db_row(name, parsed) if isinstance(parsed, dict) else {
                'number': name,
                'details': str(parsed or ''),
                'coords': coords,
            }
        except Exception:
            notam = {
                'number': name,
                'details': str(parsed or ''),
                'coords': coords,
            }

        # If coords were passed explicitly, prefer those.
        if coords:
            notam['coords'] = coords

        return render_notam_image(notam, output_path=out_path)
    except Exception:
        logger.exception("plot_single_notam failed for %s", name)
        raise
