"""NOTAM schedule (field ``D``) parsing into human-readable Russian lines.

Pure, standard-library-only logic extracted so it can be shared by both the
image composer (``starship_notam.visualization.image_composer``) and the
Telegram caption builder (``starship_notam.bot.formatting``) without pulling in
Pillow or any other heavy visualization dependency.

Public entry point:
    parse_notam_windows(raw, base=None, end=None) -> list[str]

Everything else is an implementation helper.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta


# Russian month abbreviations for compact date labels (index 1..12).
_RU_MONTHS = [
    "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]

# English month tokens (as they appear in FAA NOTAM schedules) -> month number.
# Both 3-letter abbreviations and full names are accepted.
_MONTH_TOKENS = {
    "JAN": 1, "JANUARY": 1,
    "FEB": 2, "FEBRUARY": 2,
    "MAR": 3, "MARCH": 3,
    "APR": 4, "APRIL": 4,
    "MAY": 5,
    "JUN": 6, "JUNE": 6,
    "JUL": 7, "JULY": 7,
    "AUG": 8, "AUGUST": 8,
    "SEP": 9, "SEPT": 9, "SEPTEMBER": 9,
    "OCT": 10, "OCTOBER": 10,
    "NOV": 11, "NOVEMBER": 11,
    "DEC": 12, "DECEMBER": 12,
}


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


def _day_label(day: int, base: datetime | None, month: int | None = None) -> str:
    """Return a ``Месяц DD`` label for a day-of-month.

    When ``month`` is given (resolved from an explicit month token in the
    schedule, e.g. ``SEP``/``OCT``), it is used directly. Otherwise ``base``
    (the NOTAM start datetime) supplies the month and the day is rolled into
    the next month when it is smaller than the base day.
    """
    if month is not None:
        return f"{_RU_MONTHS[month]} {day:02d}"
    if base is None:
        return f"{day:02d}"
    month = base.month
    if day < base.day:
        month += 1
        if month > 12:
            month = 1
    return f"{_RU_MONTHS[month]} {day:02d}"


def parse_notam_windows(
    raw, base: datetime | None = None, end: datetime | None = None
) -> list[str]:
    """Parse the NOTAM schedule (DB column ``D``) into display window strings.

    Returns a list of human-readable Russian lines describing each active
    window. Supported input shapes (case-insensitive), based on real feed data:

    * ``DLY 0800-2059`` / ``DAILY 2334-0300`` / ``DAILY 2200 - 0056``
      -> one ``Месяц DD, HH:MM - HH:MM`` line per active day from ``base`` (B)
      through ``end`` (C) when both are known; otherwise a single
      ``Ежедневно 08:00 - 20:59`` line.
    * ``2045/0100 DLY`` -> same daily expansion across the B..C period.
    * ``28 1223-1447`` (one per line) -> ``Сентябрь 28, 12:23 - 14:47``
    * ``20 0334-0812, 21 0320-0758`` (comma separated, may wrap)
    * ``23-28 BTN 0000-0108 2107-2359`` (day range expands to one line per day,
      each with both windows)
    * ``SEP 26-29 29-30 BTN 2107-0108`` (month token sets the month; several
      day ranges on one line share the trailing window)
    * ``30-OCT 01 01-02 02-03 04-05 DLY BTN 2107-0108`` (month rollover inside
      the line; each day gets the shared window)
    * ``SEP 26 BTN 1343-1721  27 BTN 1436-1707`` (interleaved: each day carries
      its own window on one line)
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
    #   * kind "day"   -> key is a (day, month) tuple; month may be None when
    #                     no explicit month token was present (falls back to
    #                     the ``base`` month heuristic in _day_label).
    #   * kind "plain" -> key is None (DLY / bare window with no day)
    # and ``windows`` is a list of formatted "HH:MM–HH:MM" strings for that key.
    entries: list[tuple[str, object, list[str]]] = []

    # Split into segments on newlines and commas; each segment describes one
    # or more days / day-ranges plus their shared window(s).
    segments = [seg.strip() for seg in re.split(r"[\n,]+", text) if seg.strip()]

    # Month context carries across segments: an FAA schedule states the month
    # once (e.g. "SEP ...") and later lines continue in that month until an
    # explicit rollover token ("... 30-OCT 01 ...") appears. It stays None
    # until a month token is seen so that day-only schedules keep using the
    # ``base.day`` rollover heuristic in _day_label.
    current_month: int | None = None

    for seg in segments:
        # Strip DLY/DAILY tokens; they only signal recurrence, handled below.
        seg_clean = re.sub(r"\b(DLY|DAILY)\b", " ", seg, flags=re.IGNORECASE).strip()

        # A segment may pack several "<day(s)> [BTN] <window>" groups where each
        # day carries its OWN window, e.g.
        #     "SEP 26 BTN 1343-1721  27 BTN 1436-1707  28 BTN 1315-1653"
        # Split those into per-window groups so each day pairs with the window
        # that immediately follows it, rather than sharing every window on the
        # line. Segments with a single window (or none) yield one group and
        # behave exactly as before.
        for group in _split_day_window_groups(seg_clean):
            parsed_month, day_specs, wins = _parse_segment(group, current_month)
            if parsed_month is not None:
                current_month = parsed_month

            if day_specs:
                # One or more day specifiers share this group's window(s).
                # Expand ranges to individual (day, month) pairs.
                for day, month in day_specs:
                    entries.append(("day", (day, month), list(wins)))
                continue

            # No day prefix: either "DLY HHMM-HHMM"/"HHMM/HHMM" or a bare window.
            entries.append(("plain", None, wins))

    return _format_entries(entries, base, daily, end)


def _split_day_window_groups(seg: str) -> list[str]:
    """Split a segment into ``<day(s)> [BTN] <window>`` groups.

    Some NOTAM schedules interleave day and window on one line, giving each day
    its own window::

        "SEP 26 BTN 1343-1721  27 BTN 1436-1707  28 BTN 1315-1653"

    These must be split so each day pairs only with the window that follows it.
    The split point is a window (``HHMM-HHMM`` / ``HHMM/HHMM``) that is followed
    by another day token (a bare 1-2 digit day or a month name), which signals
    the start of a new group.

    Segments in the shared-window shape are left intact, e.g.::

        "SEP 26-29 29-30 BTN 2107-0108"       # days share one trailing window
        "23-28 BTN 0000-0108 2107-2359"       # one day-range, two windows
        "28 1223-1447"                        # single day + window

    because there no day token appears after a window. Returns at least one
    group (the whole segment) when no interleaving split is found.
    """
    if not seg:
        return [seg]

    # Insert a break marker after any window that is immediately followed by a
    # new day token (1-2 digit day or a month name). The window itself stays
    # with the group that precedes it.
    window = r"\d{4}\s*[-/]\s*\d{4}"
    day_token = r"(?:\d{1,2}\b|[A-Za-z]{3,9}\b)"
    marked = re.sub(
        rf"({window})(\s+)(?={day_token})",
        r"\1\n",
        seg,
    )
    groups = [g.strip() for g in marked.split("\n") if g.strip()]
    return groups or [seg]


def _parse_segment(seg: str, current_month: int | None):
    """Parse one schedule segment into (month, day_specs, windows).

    Handles the FAA multi-day layout where several day tokens and day-ranges
    share the trailing window(s) on a single line, with optional inline month
    tokens (``SEP``/``OCT``) that set/roll the month context. Examples::

        "SEP 26-29 29-30 BTN 2107-0108"
        "30-OCT 01 01-02 02-03 03-04 04-05 BTN 2107-0108"
        "28 1223-1447"           # single day
        "23-28 BTN 0000-0108 2107-2359"

    Returns:
        month:     the last month token seen in this segment (or None), so the
                   caller can carry it forward as context.
        day_specs: ordered list of (day, month) pairs. ``month`` is the
                   resolved month for that day (may be None when unknown).
        windows:   formatted "HH:MM - HH:MM" strings shared by all day_specs.
                   For a segment with no day tokens this holds the bare/DLY
                   window(s).
    """
    # The window(s) always sit at the tail of the segment as HHMM(-|/)HHMM
    # pairs, optionally introduced by "BTN". Split the day part from the
    # window part at the first 4-digit time token.
    m_split = re.search(r"(?:\bBTN\b\s*)?(\d{4}\s*[-/]\s*\d{4}.*)$", seg, re.IGNORECASE)
    if m_split:
        day_part = seg[: m_split.start()].strip()
        win_part = m_split.group(1)
    else:
        day_part = ""
        win_part = seg

    windows = _windows_in(win_part.replace("/", "-"))

    # No day tokens -> plain/bare/DLY window segment.
    if not day_part:
        return None, [], windows

    day_specs: list[tuple[int, int | None]] = []
    month = current_month
    last_month_seen: int | None = None

    # Tokenize the day part on whitespace. Each token is one of:
    #   * a month name          -> updates the running month
    #   * "DD"                  -> a single day
    #   * "DD-DD"               -> a same-month day range
    #   * "DD-MON" / "MON DD"   -> a cross-month boundary (handled via the
    #                              range logic below)
    tokens = day_part.split()
    i = 0
    while i < len(tokens):
        tok = tokens[i].upper().strip("-")
        # Bare month token: set context for following days.
        if tok in _MONTH_TOKENS:
            month = _MONTH_TOKENS[tok]
            last_month_seen = month
            i += 1
            continue

        # Range with a month rollover inside it: "DD-MON" followed by "DD".
        m_dm = re.fullmatch(r"(\d{1,2})-([A-Z]{3,9})", tok)
        if m_dm and m_dm.group(2) in _MONTH_TOKENS:
            d1 = int(m_dm.group(1))
            m2 = _MONTH_TOKENS[m_dm.group(2)]
            d2 = None
            if i + 1 < len(tokens) and re.fullmatch(r"\d{1,2}", tokens[i + 1]):
                d2 = int(tokens[i + 1])
                i += 1
            _emit_cross_month(day_specs, d1, month, d2, m2)
            month = m2
            last_month_seen = m2
            i += 1
            continue

        # Same-month range: "DD-DD".
        m_rng = re.fullmatch(r"(\d{1,2})-(\d{1,2})", tok)
        if m_rng:
            d1, d2 = int(m_rng.group(1)), int(m_rng.group(2))
            if 1 <= d1 <= 31 and 1 <= d2 <= 31:
                for d in _expand_day_range(d1, d2):
                    # A wrap (e.g. 30-02) rolls into the next month.
                    mo = month
                    if mo is not None and d < d1:
                        mo = mo + 1 if mo < 12 else 1
                    day_specs.append((d, mo))
            i += 1
            continue

        # Single day: "DD".
        m_one = re.fullmatch(r"\d{1,2}", tok)
        if m_one and 1 <= int(tok) <= 31:
            day_specs.append((int(tok), month))
        i += 1

    return last_month_seen if last_month_seen is not None else month, day_specs, windows


def _emit_cross_month(day_specs, d1: int, m1: int | None, d2: int | None, m2: int) -> None:
    """Append days for a range that crosses a month boundary (``DD-MON DD``).

    ``d1`` is in month ``m1`` (the running month) and the range runs up to
    ``d2`` in month ``m2``. When ``d2`` is unknown only the start day is added.
    """
    day_specs.append((d1, m1))
    if d2 is None:
        return
    # Fill the tail of the first month (d1+1 .. up to 31) then the start of the
    # second month (1 .. d2). We don't know the exact length of month m1, so we
    # stop the first-month fill once we would exceed a plausible month end; the
    # de-duplication downstream tolerates a spurious 31 only when it is a real
    # calendar day, which _day_label renders verbatim. To stay safe we only
    # bridge directly to the second month's days.
    for d in range(1, d2 + 1):
        day_specs.append((d, m2))


def _windows_in(rest: str) -> list[str]:
    """Extract all ``HHMM-HHMM`` pairs in ``rest`` as ``HH:MM–HH:MM`` strings."""
    out: list[str] = []
    for start_tok, end_tok in re.findall(r"(\d{4})\s*-\s*(\d{4})", rest):
        win = _fmt_window(start_tok, end_tok)
        if win is not None:
            out.append(win)
    return out


def _format_entries(
    entries, base: datetime | None, daily: bool, end: datetime | None = None
) -> list[str]:
    """Turn parsed schedule entries into display lines.

    Each entry produces one line per window in the form
    ``Месяц DD, HH:MM - HH:MM`` (e.g. ``Сентябрь 28, 12:23 - 14:47``). Every
    day is listed on its own line; consecutive identical days are NOT collapsed
    into ranges. Day ranges are already expanded to individual ``day`` entries
    upstream (see ``_parse_segment``), each carrying its resolved month.

    For a ``DLY``/``DAILY`` schedule with no explicit day tokens, the window(s)
    are expanded to one line per calendar day from ``base`` (field B) through
    ``end`` (field C) when both are known, so the reader sees the concrete set
    of active dates instead of a bare ``Ежедневно`` line. If either bound is
    missing we fall back to the single ``Ежедневно`` line.
    """
    lines: list[str] = []
    for kind, key, wins in entries:
        if not wins:
            continue

        if kind == "day":
            day, month = key
            label = _day_label(day, base, month)
            for w in wins:
                lines.append(f"{label}, {w}")
        elif daily and base is not None and end is not None:
            # Expand the daily window across every active day of the B..C
            # period, one line per day.
            for day_dt in _iter_days(base, end):
                label = f"{_RU_MONTHS[day_dt.month]} {day_dt.day:02d}"
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


def _iter_days(start: datetime, end: datetime):
    """Yield one ``datetime`` per calendar day from ``start`` to ``end``.

    Both endpoints are inclusive at the date level (times are ignored). Used to
    expand a ``DLY``/``DAILY`` window into an explicit per-day list across the
    NOTAM's B..C period.
    """
    day = start.date()
    last = end.date()
    while day <= last:
        yield datetime(day.year, day.month, day.day)
        day += timedelta(days=1)


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
