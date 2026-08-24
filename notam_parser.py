import re
import json
from datetime import datetime
from typing import Dict, Optional, List, Any
from notam_logging import logger
from notam_db import save_notam


def _find_fields(text: str) -> Dict[str, str]:
    # Find labels like "Q)", "A)", "B)", ... up to "G)" and capture content between them.
    # Labels may appear at line start or inline (e.g. "B) 2605152321 C) 2605220248").
    # Labels must appear at start or after whitespace to avoid false positives inside words
    # (e.g. "AREA)" should not be read as "A)").
    pattern = re.compile(r'(^|\s)(?P<label>[QABCDEFG])\)\s*', re.MULTILINE)
    raw_matches = list(pattern.finditer(text))

    # Enforce forward label order: Q -> A -> B -> C -> D -> E -> F -> G
    ordered_labels = ['Q', 'A', 'B', 'C', 'D', 'E', 'F', 'G']
    matches = []
    last_idx = -1
    for m in raw_matches:
        label = m.group('label')
        idx = ordered_labels.index(label)
        if idx > last_idx:
            matches.append(m)
            last_idx = idx
        else:
            logger.debug(f"Ignoring out-of-order or duplicate field marker: {label})")

    fields = {}
    if not matches:
        # fallback: place entire text into E
        logger.info("No labelled fields found; falling back to E) with full text")
        fields['E'] = text.strip()
        return fields

    for i, m in enumerate(matches):
        label = m.group('label')
        start = m.end()
        end = matches[i+1].start() if i+1 < len(matches) else len(text)
        content = text[start:end].strip()
        fields[label] = content
        logger.debug(f"Found field {label}) with {len(content)} chars")

    return fields


def _try_parse_dt(s: str) -> Optional[str]:
    if s is None:
        return None
    # Coerce non-string inputs (e.g., numeric JSON values) to string
    if not isinstance(s, str):
        s = str(s)
    s = s.strip()
    # common NOTAM formats: YYYYMMDDhhmm, YYMMDDhhmm, YYYYMMDDThhmm, YYYY-MM-DDTHH:MMZ
    fmt_candidates = [
        '%Y%m%d%H%M', '%y%m%d%H%M', '%Y%m%dT%H%M', '%y%m%dT%H%M', '%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M'
    ]
    # remove obvious noise but keep digits, T, Z, colon, dash and space
    cleaned = re.sub(r'(?i)[^0-9TZt:\-:\s]', '', s)

    # Extract all compact numeric tokens (12-digit YYYYMMDDHHMM or 10-digit YYMMDDHHMM)
    tokens = re.findall(r'\d{12}|\d{10}', cleaned)

    # Try parsing each token in a sensible order
    for token in tokens:
        try:
            if len(token) == 12:
                dt = datetime.strptime(token, '%Y%m%d%H%M')
                parsed = dt.isoformat() + 'Z'
                logger.debug(f"Parsed datetime token '{token}' from '{s}' as {parsed} using %Y format")
                return parsed
            elif len(token) == 10:
                # Interpret 10-digit token as YYMMDDHHMM (e.g., 2106231700 -> 2021-06-23T17:00Z)
                dt = datetime.strptime(token, '%y%m%d%H%M')
                parsed = dt.isoformat() + 'Z'
                logger.debug(f"Parsed datetime token '{token}' from '{s}' as {parsed} using %y format")
                return parsed
        except Exception:
            continue

    # Fallback: try candidate formats against the cleaned string
    for fmt in fmt_candidates:
        try:
            dt = datetime.strptime(cleaned, fmt)
            parsed = dt.isoformat() + 'Z'
            logger.debug(f"Parsed datetime '{s}' as {parsed} using fmt {fmt}")
            return parsed
        except Exception:
            continue

    logger.info(f"Could not parse datetime string: {s}; returning raw")
    return s


def _parse_q_line(q: str) -> Dict[str, Optional[str]]:
    """Parse the Q) qualifier line into components.

    Typical Q) content: <location>/<qcode>/<traffic>/<traffic_rule>/<lower>/<upper>/<latlon><radius>
    This function uses heuristics to extract the most common pieces.
    """
    out = {
        'raw': q,
        'location': None,
        'q_code': None,
        'traffic': None,
        'traffic_rule': None,
        'lower': None,
        'upper': None,
        'coordinates': None,
        'radius_nm': None,
    }
    parts = [p.strip() for p in q.split('/') if p.strip()]
    if not parts:
        return out

    # first part often the FIR/location
    out['location'] = parts[0]
    if len(parts) > 1:
        out['q_code'] = parts[1]
    if len(parts) > 2:
        out['traffic'] = parts[2]
    if len(parts) > 3:
        out['traffic_rule'] = parts[3]

    # remaining parts may include lower/upper limits and coordinates
    for p in parts[4:]:
        # altitude fields are often three-digit or three-digit with leading zeros
        if re.fullmatch(r'\d{3,4}', p):
            if out['lower'] is None:
                out['lower'] = p
            elif out['upper'] is None:
                out['upper'] = p
            continue

        # coordinates with trailing radius (e.g., 4008N07400W005)
        m = re.search(r'([0-9]{4,6}[NS].*?[0-9]{5,6}[EW])(\d{2,3})?$', p)
        if m:
            out['coordinates'] = m.group(1)
            if m.group(2):
                out['radius_nm'] = m.group(2)
            logger.debug(f"Parsed Q) coordinates: {out['coordinates']} radius: {out.get('radius_nm')}")
            continue

        # sometimes coordinates are space-separated lat lon and radius
        m2 = re.search(r'([0-9]{2,4}[NS])\s*([0-9]{3,5}[EW])\s*(\d{2,3})', p)
        if m2:
            out['coordinates'] = m2.group(1) + ' ' + m2.group(2)
            out['radius_nm'] = m2.group(3)
            logger.debug(f"Parsed Q) coordinates (space): {out['coordinates']} radius: {out['radius_nm']}")
            continue

    return out


def parse_notam(text: str) -> Dict[str, str]:
    """Parse an ICAO-style NOTAM text into a dictionary with keys Q,A,B,C,D,E,F,G.

    The parser is tolerant: it captures field blocks beginning with labels like "Q)", "A)", etc.
    If no labels are found it places the whole text under `E`.
    """
    # detect CARF/TFR-style messages starting with a leading bang (e.g. "!CARF ...", "!FDC ...")
    try:
        if re.search(r'^\s*!(CARF|FDC)\b', text, re.IGNORECASE):
            return parse_carf_message(text)
    except Exception:
        # fall back to labelled-field parsing on any error
        logger.debug('CARF autodetect failed; falling back to labelled-field parsing')

    fields = _find_fields(text)
    parsed = {}
    # copy raw fields
    for k, v in fields.items():
        parsed[k] = v

    # normalize B and C into ISO where possible (overwrite original field)
    if 'B' in fields:
        parsed['B'] = _try_parse_dt(fields['B'])
    if 'C' in fields:
        parsed['C'] = _try_parse_dt(fields['C'])

    # attempt to parse Q) qualifier into structured subfields if present
    if 'Q' in fields:
        parsed['Q'] = _parse_q_line(fields['Q'])

    # ensure E exists
    if 'E' not in parsed:
        parsed['E'] = fields.get('E', '')
        logger.debug("E) field set from parsed fields")


    return parsed


def _dms_to_decimal(dms: str) -> Optional[float]:
    """Convert a compact DMS string (e.g. 260000 -> 26°00'00") to decimal degrees."""
    if not dms or not dms.isdigit():
        return None
    # handle variable-length degree portions (lat may be 4-6 digits, lon 5-7)
    L = len(dms)
    if L < 4:
        return None
    # degrees are the leading digits before the last 4 (mmss)
    deg_part = dms[:-4]
    min_part = dms[-4:-2]
    sec_part = dms[-2:]
    try:
        deg = int(deg_part) if deg_part else 0
        minu = int(min_part)
        sec = int(sec_part)
    except Exception:
        return None
    return deg + minu / 60.0 + sec / 3600.0


def _parse_coord_pair(token: str) -> Optional[Dict[str, float]]:
    """Parse a single compact coordinate token like 260000N0955500W into decimal lat/lon."""
    m = re.match(r'(?P<lat>\d{4,6})(?P<latdir>[NS])(?P<lon>\d{5,7})(?P<londir>[EW])', token)
    if not m:
        return None
    lat = _dms_to_decimal(m.group('lat'))
    lon = _dms_to_decimal(m.group('lon'))
    if lat is None or lon is None:
        return None
    if m.group('latdir') == 'S':
        lat = -lat
    if m.group('londir') == 'W':
        lon = -lon
    return {'raw': token, 'lat': lat, 'lon': lon}


def _parse_polygon_from_chain(chain: str) -> List[Dict[str, float]]:
    """Given a coordinate chain like '260000N0955500W TO 255900N0954800W',
    return a list of parsed point dicts.
    """
    coord_re = re.compile(r'\d{4,6}[NS]\d{5,7}[EW]')
    matches = coord_re.findall(chain)
    out = []
    for t in matches:
        p = _parse_coord_pair(t)
        if p:
            out.append(p)
    return out


def _extract_coord_chain(text: str) -> Optional[str]:
    """Extract a coordinate chain from free-form TFR/CARF text.

    The chain may contain annotations in parentheses after each coordinate and
    may end before a validity window like ``2607081350-2607160500``.
    """
    coord_re = re.compile(r'\d{4,6}[NS]\d{5,7}[EW]')
    window_re = re.compile(r'\d{10,12}-\d{10,12}')

    first = coord_re.search(text)
    if not first:
        return None

    tail = text[first.start():]
    window = window_re.search(tail)
    if window:
        tail = tail[:window.start()]

    coords = coord_re.findall(tail)
    if not coords:
        return None

    return ' TO '.join(coords)


def _extract_altitude(text: str) -> Optional[str]:
    """Best-effort extraction of a TFR altitude block.

    Supports common forms like ``SFC-5000FT AGL ONLY`` or ``FL180-FL240``.
    """
    altitude_info = _parse_tfr_altitude(text)
    if altitude_info:
        return altitude_info['raw']
    return None


def _normalize_altitude_token(token: str) -> Dict[str, Optional[str]]:
    token = ' '.join(token.upper().split()).strip(' ,.;')
    if token in {'SFC', 'GND', 'GROUND'}:
        return {
            'raw': token,
            'display': 'SFC',
            'description': 'surface',
            'units': None,
            'reference': None,
        }

    m = re.fullmatch(r'FL(?P<fl>\d{2,3})', token)
    if m:
        return {
            'raw': token,
            'display': f"FL{m.group('fl')}",
            'description': f"flight level {m.group('fl')}",
            'units': 'FL',
            'reference': None,
        }

    m = re.fullmatch(r'(?P<feet>\d{1,5})(?:\s*FT)?(?:\s*(?P<reference>AGL|MSL|AMSL|ASL))?', token)
    if m:
        feet = m.group('feet')
        reference = m.group('reference')
        descriptions = {
            'AGL': 'above ground level',
            'MSL': 'mean sea level',
            'AMSL': 'above mean sea level',
            'ASL': 'above sea level',
        }
        display = f"{feet} {reference}" if reference else f"{feet} FT"
        return {
            'raw': token,
            'display': display,
            'description': descriptions.get(reference),
            'units': 'FT',
            'reference': reference,
        }

    return {
        'raw': token,
        'display': token,
        'description': None,
        'units': None,
        'reference': None,
    }


def _parse_tfr_altitude(text: str) -> Optional[Dict[str, Any]]:
    """Extract and normalize a TFR altitude block.

    The return value keeps the original text while exposing a flattened
    min/max representation that is easy to display and persist.
    """
    altitude_patterns = [
        r'\b(?P<lower>SFC|GND|GROUND|FL\d{2,3}|\d{1,5}(?:\s*FT)?)\s*-\s*(?P<upper>FL\d{2,3}|\d{1,5}(?:\s*FT)?(?:\s*(?:AGL|MSL|AMSL|ASL))?)(?:\s+ONLY)?',
    ]
    for pattern in altitude_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if not m:
            continue

        lower = _normalize_altitude_token(m.group('lower'))
        upper = _normalize_altitude_token(m.group('upper'))
        raw = ' '.join(m.group(0).split()).strip(' ,.;')
        out: Dict[str, Any] = {
            'raw': raw,
            'min': lower['display'],
            'min_description': lower['description'],
            'max': upper['display'],
            'max_description': upper['description'],
            'min_units': lower['units'],
            'max_units': upper['units'],
            'min_reference': lower['reference'],
            'max_reference': upper['reference'],
        }
        if upper['reference']:
            out['reference'] = upper['reference']
        return out

    return None


def _extract_circle_definition(text: str) -> Optional[Dict[str, Any]]:
    """Extract circle-style area definitions like "2.5NM RADIUS OF 255950N0970921W"."""
    m = re.search(
        r'(?P<radius>\d+(?:\.\d+)?)\s*NM\s+RADIUS\s+OF\s+(?P<center>\d{4,6}[NS]\d{5,7}[EW])',
        text,
        re.IGNORECASE,
    )
    if not m:
        return None

    center_token = m.group('center').upper()
    center = _parse_coord_pair(center_token)
    return {
        'radius_nm': m.group('radius'),
        'center_raw': center_token,
        'center': center,
    }


def parse_carf_message(text: str) -> Dict[str, Any]:
    """Parse informal CARF-style messages that begin with a leading '!'.

    Returns a dict with keys: source, notam_id, artcc, operation, polygon (list),
    altitude (raw), altitude min/max aliases, validity_start, validity_end and
    original text in E.
    Also populates a minimal `Q` sub-dict so downstream DB code can store coordinates.
    """
    s = ' '.join(text.strip().split())
    toks = s.split(' ')
    out: Dict[str, Any] = {'raw': text.strip(), 'E': text.strip()}

    # source
    if toks and toks[0].startswith('!'):
        out['source'] = toks[0][1:].upper()
    else:
        out['source'] = None

    # notam id and artcc (best-effort token positions)
    notam_id = None
    artcc = None
    if len(toks) > 1 and re.match(r'^\d{1,2}/\d{1,4}$', toks[1]):
        notam_id = toks[1]
        if len(toks) > 2:
            artcc = toks[2]
            op_start_idx = 3
        else:
            op_start_idx = 2
    else:
        # fallback: try to find an ID-like token anywhere
        for i, t in enumerate(toks[1:], start=1):
            if re.match(r'^\d{1,2}/\d{1,4}$', t):
                notam_id = t
                artcc = toks[i+1] if i+1 < len(toks) else None
                op_start_idx = i+2
                break
        else:
            op_start_idx = 1

    out['notam_id'] = notam_id
    out['artcc'] = artcc

    # find first coordinate token to delimit the operation string
    coord_re = re.compile(r'^\d{4,6}[NS]\d{5,7}[EW]$')
    coord_index = None
    for i in range(op_start_idx, len(toks)):
        if coord_re.match(toks[i].strip(',.')):
            coord_index = i
            break

    remainder = ' '.join(toks[op_start_idx:]).strip()
    circle_def = _extract_circle_definition(remainder)
    chain_str = _extract_coord_chain(remainder)
    altitude_info = _parse_tfr_altitude(remainder)
    window_match = re.search(r'(\d{10,12})-(\d{10,12})', remainder)

    if altitude_info:
        out['altitude'] = altitude_info['raw']
        out['altitude_min'] = altitude_info['min']
        out['altitude_min_description'] = altitude_info['min_description']
        out['altitude_max'] = altitude_info['max']
        out['altitude_max_description'] = altitude_info['max_description']
        if altitude_info.get('min_units'):
            out['altitude_min_units'] = altitude_info['min_units']
        if altitude_info.get('max_units'):
            out['altitude_max_units'] = altitude_info['max_units']
        if altitude_info.get('min_reference'):
            out['altitude_min_reference'] = altitude_info['min_reference']
        if altitude_info.get('max_reference'):
            out['altitude_max_reference'] = altitude_info['max_reference']
        if altitude_info.get('reference'):
            out['altitude_reference'] = altitude_info['reference']

    if chain_str is None:
        # no coordinates found: operation is the remainder
        out['operation'] = remainder
        out['polygon'] = []
        out['Q'] = {}
    else:
        first_coord = re.search(r'\d{4,6}[NS]\d{5,7}[EW]', remainder)
        op_text = remainder[:first_coord.start()] if first_coord else remainder
        out['operation'] = ' '.join(op_text.split()).strip(' ,.;')

        out['polygon_raw'] = chain_str
        out['polygon'] = _parse_polygon_from_chain(chain_str)
        # Also populate Q) like structure so DB can index coordinates.
        # For circle definitions, store center token + radius separately.
        q = {'coordinates': chain_str}
        if circle_def:
            q['coordinates'] = circle_def['center_raw']
            q['radius_nm'] = circle_def['radius_nm']
            out['radius_nm'] = circle_def['radius_nm']
            out['center'] = circle_def.get('center')
        out['Q'] = q

        alt_token = _extract_altitude(remainder)
        if alt_token:
            out['altitude'] = alt_token
            try:
                lower, upper = alt_token.split('-', 1)
                out['Q']['lower'] = lower.strip()
                out['Q']['upper'] = upper.strip()
            except Exception:
                pass

        if altitude_info:
            out['Q']['lower'] = altitude_info['min']
            out['Q']['upper'] = altitude_info['max']

    if window_match:
        out['validity_start'] = _try_parse_dt(window_match.group(1))
        out['validity_end'] = _try_parse_dt(window_match.group(2))
        out['effective'] = out['validity_start']
        out['expires'] = out['validity_end']
        out['B'] = out['validity_start']
        out['C'] = out['validity_end']

    return out


def save_notam_json(parsed: Dict[str, str], path) -> None:
    """Persist parsed NOTAM. If `path` is a Path inside the notams/ dir we use its
    stem as the NOTAM name and save into the SQLite DB. Kept the function name for
    backwards compatibility with callers in this repo.
    """
    # derive a stable name from provided path (e.g. 'A0669_26.json' -> 'A0669_26')
    try:
        name = getattr(path, 'stem', None) or str(path)
        # convert filesystem-safe names back to a display name if they used underscores
        name = name
    except Exception:
        name = str(path)

    try:
        save_notam(name, parsed)
        # logger.info(f"Saved parsed NOTAM to DB as: {name}")
    except Exception as e:
        logger.exception(f"Failed to save NOTAM to DB for {name}: {e}")


if __name__ == '__main__':
    sample = '''
    !FDC 6/3895 ZHU TX..AIRSPACE BROWNSVILLE, TX..TEMPORARY FLIGHT RESTRICTIONS. PURSUANT TO 14 CFR SECTION 91.137(A)(1) GROUND HAZARD WI AN AREA DEFINED AS 255720N0970928W (BRO072011.9) TO 255728N0971011W (BRO071011.3) TO 255746N0971051W (BRO068010.8) TO 255815N0971128W (BRO065010.3) TO 255843N0971149W (BRO062010.2) TO 255923N0971147W (BRO059010.4) TO 255923N0971204W (BRO058010.2) TO 255832N0971643W (BRO050006.1) TO 255644N0971640W (BRO067005.4) TO 255720N0970928W (BRO072011.9) TO POINT OF ORIGIN SFC-5000FT AGL ONLY RELIEF ACFT OPS UNDER DIRECTION OF SPACEX ARE AUTH IN THE AIRSPACE. SPACEX, KYLE HURN TEL 956-346-8311 IS IN CHARGE OF ON SCENE EMERG RESPONSE ACTIVITY. HOUSTON/ZHU/ARTCC TEL 281-230-5560 IS THE FAA CDN FAC. 2607081350-2607160500
    '''
    print(parse_notam(sample))
