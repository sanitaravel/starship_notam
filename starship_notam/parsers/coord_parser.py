"""Coordinate parsing utilities: DMS, decimal, and polygon extraction.

Pure-function module with no I/O dependencies.
Only uses standard library modules (re, typing).
"""

from __future__ import annotations

import re
from typing import Union


def _dms_token_to_decimal(tok: str) -> float | None:
    """Convert tokens like '195700N' or '0820100W' to decimal degrees.

    Supports:
    - 4 digits: DDMM (degrees, minutes)
    - 5 digits: DDDMM (degrees may be 3 digits for longitudes)
    - 6 digits: DDMMSS (degrees, minutes, seconds)
    - 7 digits: DDDMMSS
    Returns None on parse/validation failure.
    """
    m = re.match(r"(\d{4,7})([NSWE])", tok, re.IGNORECASE)
    if not m:
        return None
    digits = m.group(1)
    dirc = m.group(2).upper()
    try:
        if len(digits) >= 6:
            # deg + min + sec (e.g. 195700 -> 19,57,00)
            secs = int(digits[-2:])
            mins = int(digits[-4:-2])
            deg = int(digits[:-4]) if digits[:-4] else 0
        elif len(digits) == 5:
            # treat as DDDMM (e.g. 12345 -> 123 deg, 45 min)
            deg = int(digits[:-2])
            mins = int(digits[-2:])
            secs = 0
        else:  # len == 4
            deg = int(digits[:2])
            mins = int(digits[2:])
            secs = 0
    except Exception:
        return None

    # basic validation
    if not (0 <= mins < 60 and 0 <= secs < 60 and deg >= 0):
        return None

    dec = deg + mins / 60.0 + secs / 3600.0
    if dirc in ("S", "W"):
        dec = -dec

    # enforce plausible ranges for lat/lon depending on direction
    if dirc in ("N", "S") and abs(dec) > 90 + 1e-8:
        return None
    if dirc in ("E", "W") and abs(dec) > 180 + 1e-8:
        return None
    return dec


def _parse_coords(raw: str) -> list[tuple[float, float]] | None:
    """Try to parse coordinates from free text into (lat, lon) floats.

    Strategies (in order):
    - DMS paired lat/lon like '1500N06500W' or '195700N0820100W'
    - Standalone DMS tokens paired by direction (e.g. '2358S' then '07500E')
    - Split DMS like '23 58S 075 00E'
    - Decimal comma-separated pairs like '12.345, 67.890'
    - Whitespace-separated decimal pairs like '12.345 67.890'

    Returns a list of (lat, lon) tuples, or None if nothing could be parsed.
    """
    if not raw:
        return None

    s = str(raw)
    coords_out: list[tuple[float, float]] = []

    # 1) Look for contiguous lat/lon DMS pairs like '1500N06500W',
    #    or with seconds like '195700N0820100W'. Accept 4..7 digit
    #    DMS tokens (DDMM, DDDMM, DDMMSS, DDDMMSS) followed by N/S/E/W.
    pair_latlon_re = re.compile(
        r"(\d{4,7}[NS])\s*[,;:/\-\u2013\u2014]?\s*(\d{4,7}[EW])", re.IGNORECASE
    )

    for m in pair_latlon_re.finditer(s):
        lat_tok, lon_tok = m.group(1), m.group(2)
        lat = _dms_token_to_decimal(lat_tok)
        lon = _dms_token_to_decimal(lon_tok)
        if lat is not None and lon is not None:
            coords_out.append((lat, lon))
    if coords_out:
        return coords_out

    # 2) Look for standalone DMS tokens (e.g. '2358S' or '07500E') and pair them
    token_re = re.compile(r"(\d{4,7})([NSWE])", re.IGNORECASE)
    tokens = token_re.findall(s)
    if tokens:
        lat_val: float | None = None
        lon_val: float | None = None
        for digits, dirc in tokens:
            dec = _dms_token_to_decimal(digits + dirc)
            if dec is None:
                continue
            dirc = dirc.upper()
            if dirc in ("N", "S"):
                lat_val = dec
            elif dirc in ("E", "W"):
                lon_val = dec
            if lat_val is not None and lon_val is not None:
                coords_out.append((lat_val, lon_val))
                lat_val = None
                lon_val = None
        if coords_out:
            return coords_out

    # 3) Try to find patterns like '23 58S 075 00E' (split numbers with directions)
    parts = re.findall(r"([0-9]{1,3}\s*[0-9]{2}\s*[NSWE])", s, flags=re.IGNORECASE)
    if parts:
        # attempt simple parsing by removing spaces and reusing token_re
        for p in parts:
            m_tok = token_re.search(p)
            if m_tok:
                # reuse above logic by calling recursively
                res = _parse_coords(m_tok.group(0))
                if res:
                    return res

    # 4) Try to find explicit decimal coordinate pairs like 'lat, lon' or 'lat lon'
    pair_re = re.compile(r"([-+]?[0-9]*\.?[0-9]+)\s*,\s*([-+]?[0-9]*\.?[0-9]+)")
    for m in pair_re.finditer(s):
        try:
            lat = float(m.group(1))
            lon = float(m.group(2))
            coords_out.append((lat, lon))
        except Exception:
            continue
    if coords_out:
        return coords_out

    # also try whitespace-separated decimal pairs (less strict)
    ws_pair_re = re.compile(r"([-+]?[0-9]*\.?[0-9]+)\s+([-+]?[0-9]*\.?[0-9]+)")
    for m in ws_pair_re.finditer(s):
        try:
            lat = float(m.group(1))
            lon = float(m.group(2))
            coords_out.append((lat, lon))
        except Exception:
            continue
    if coords_out:
        return coords_out

    return None


def parse_coords_from_text(
    raw: str,
) -> Union[list[tuple[float, float]], tuple[float, float], None]:
    """Parse coordinate data from free-form text.

    Returns:
        - A list of (lat, lon) pairs for polygons/multi-points
        - A single (lat, lon) tuple if only one pair was found
        - None when no coordinates could be parsed
    """
    try:
        res = _parse_coords(raw)
        if not res:
            return None
        # _parse_coords returns a list of pairs when it finds coordinates.
        if isinstance(res, list):
            if len(res) == 1:
                return tuple(res[0])
            return res
        return res
    except Exception:
        return None
