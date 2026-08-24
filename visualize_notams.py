from PIL import Image, ImageDraw, ImageFont
import io
import os
from pathlib import Path
from datetime import datetime, timezone
from notam_logging import logger

# Canvas and layout constants
CANVAS_W = 1316
CANVAS_H = 711
PADDING = 24

# Right map fixed size
MAP_W = 743
MAP_H = 662

# Map extent scale: values >1 slightly zoom out (makes NOTAM area appear smaller)
MAP_EXTENT_SCALE = 2

# Left width constraint
LEFT_MAX_W = 444

# Colors
# Background color updated to #262626 (38,38,38)
BG_COLOR = (38, 38, 38)
WHITE = (254, 254, 254)
GRAY_AAA = (170, 170, 170)
RED_CF = (207, 0, 0)


def load_font(name: str, size: int, weight: str = None):
    # Prefer fonts shipped in the project's `fonts/` directory, then system fonts
    project_fonts = Path(__file__).parent / "fonts"
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


def _parse_coords(raw: str):
    """Try to parse coordinates from free text into (lat, lon) floats.

    Strategies:
    - Decimal numbers: '12.345, 67.890' or '12.345 67.890'
    - DMS shorthand like '2358S 07500E' (DDMM[N/S] DDDMM[E/W])
    - Multiple pairs: return first lat/lon pair found
    """
    if not raw:
        return None
    import re

    s = str(raw)

    coords_out = []
    
    # 2) Look for contiguous lat/lon DMS pairs like '1500N06500W',
    #    or with seconds like '195700N0820100W'. Accept 4..7 digit
    #    DMS tokens (DDMM, DDDMM, DDMMSS, DDDMMSS) followed by N/S/E/W.
    pair_latlon_re = re.compile(r"(\d{4,7}[NS])\s*[,;:\-\u2013\u2014]?\s*(\d{4,7}[EW])", re.IGNORECASE)

    def _dms_token_to_decimal(tok: str):
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

    for m in pair_latlon_re.finditer(s):
        lat_tok, lon_tok = m.group(1), m.group(2)
        lat = _dms_token_to_decimal(lat_tok)
        lon = _dms_token_to_decimal(lon_tok)
        if lat is not None and lon is not None:
            coords_out.append((lat, lon))
    if coords_out:
        logger.info("Parsed %d coordinate pairs from DMS lat/lon regex", len(coords_out))
        logger.info("Parsed coordinates: %s", coords_out)
        return coords_out
    
    # 3) Look for standalone DMS tokens (e.g. '2358S' or '07500E') and pair them
    token_re = re.compile(r"(\d{4,5})([NSWE])", re.IGNORECASE)
    tokens = token_re.findall(s)
    if tokens:
        lat_val = None
        lon_val = None
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
            m = token_re.search(p)
            if m:
                # reuse above logic by calling recursively
                res = _parse_coords(m.group(0))
                if res:
                    return res

    # 1) Try to find explicit decimal coordinate pairs like 'lat, lon' or 'lat lon'
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

def parse_coords_from_text(raw):
    """Public wrapper around the internal coordinate parser.

    Returns a list of (lat, lon) pairs for polygons/multi-points,
    a single (lat, lon) tuple if only one pair was found, or
    None when no coordinates could be parsed.
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
        logger.exception("parse_coords_from_text failed")
        return None


def plot_single_notam(name: str, parsed: dict, coords, out_path: str, _unused=None):
    """Blocking helper used by external callers to generate a NOTAM image.

    This function is suitable for running in a thread (e.g. via
    `asyncio.to_thread`) and simply wraps existing helpers to produce
    the file at `out_path` and return that path.
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

        return render_notam_image(notam, out_path=out_path)
    except Exception:
        logger.exception("plot_single_notam failed for %s", name)
        raise


def _parse_notam_time(raw):
    """Parse various NOTAM time formats into a datetime (UTC) or None."""
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw
    s = str(raw).strip()
    import re

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

import re

def extract_starship_template(notam: str) -> str | None:
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
    flight = None

    patterns = [
        r"STARSHIP\s+FLT[- ]?(\d+)",
        r"STARSHIP\s+FLT[-]?(\d+)",
        r"STARSHIP\s+FLIGHT\s+(\d+)",
        r"STARSHIP\s+FLIGHT-(\d+)",
        r"SPACEX\s+STARSHIP\s+FLT[- ]?(\d+)",
        r"SPACEX\s+STARSHIP\s+FLIGHT\s+(\d+)",
    ]

    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            flight = m.group(1)
            break

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
        "REENTRY" in text
        and "SPLASHDOWN" in text
    ):
        return (
            f"ЗОНА ВХОДА В АТМОСФЕРУ И ПРИВОДНЕНИЯ "
            f"КОСМИЧЕСКОГО КОРАБЛЯ SPACEX STARSHIP "
            f"FLT-{flight}"
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
        "DEBRIS RESPONSE AREAS","HAZARDOUS OPERATION",
        
        "FALLING DEBRIS",
        "POSSIBILITY OF FALLING DEBRIS",
        "ACFT HAZARD AREA",
        "DUE LAUNCH OF SPACEX STARSHIP",
        "DUE TO THE LAUNCH OF THE",
        "TEMPORARY DANGER AREAS"
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

    return None

def _notam_from_db_row(name: str, parsed: dict):
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
        # Coordinates: always derive polygon/point from the E/D text (raw), not from Q)
        coords = _parse_coords(raw)
        radius_nm = None
        if isinstance(coords, list) and len(coords) == 1:
            # Treat one parsed DMS coordinate as a point center.
            coords = tuple(coords[0])
        if isinstance(coords, list) and coords:
            logger.info("Parsed %d coordinates from E field/text", len(coords))
        elif isinstance(coords, tuple) and coords:
            logger.info("Parsed center coordinate from E field/text")
        # extract zone code and upper limit (top height) if available
        zone_code = None
        top_limit = None
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
            raw = name.strip()
            if raw.lower().endswith('.json'):
                raw = raw[:-5]
            number = raw.replace('_', '/')
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

    return {
        'number': number,
        'details': details or '',
        'coords': coords,
        'radius_nm': radius_nm,
        'meta': '(ДЛЯ ВОЗДУШНОГО ТРАНСПОРТА)',
        'author': '@sanitaravel',
        'start': start_str,
        'end': end_str,
        # Q) derived fields
        'zone': zone_code,
        'top': top_limit,
    }


def render_map_image(coords, size=(MAP_W, MAP_H), radius_nm=None):
    """Render a map image (PIL.Image) showing the given coords polygon or point using Cartopy.

    Returns an RGBA PIL Image of exact `size`. Raises on import/render errors.
    """
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import cartopy.crs as ccrs
        import cartopy.feature as cfeature
        from shapely.geometry import Polygon, Point
    except Exception as e:
        logger.exception("Cartopy/Matplotlib not available: %s", e)
        raise

    fig_dpi = 100
    fig_w = size[0] / fig_dpi
    fig_h = size[1] / fig_dpi
    logger.info("Creating map figure with size %dx%d pixels (%.2fx%.2f inches at %d DPI)", size[0], size[1], fig_w, fig_h, fig_dpi)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=fig_dpi, subplot_kw=dict(projection=ccrs.PlateCarree()))
    # fill background
    # Match figure and axes background to the canvas ocean color (#262626)
    fig.patch.set_facecolor('#262626')
    ax.set_facecolor('#262626')
    # Some GeoAxes implementations may not have outline_patch; guard access
    try:
        if hasattr(ax, 'outline_patch') and ax.outline_patch is not None:
            ax.outline_patch.set_visible(False)
    except Exception:
        logger.exception("Failed to hide axes outline, map may have unexpected border")
        pass

    # compute extent
    radius_value = None
    try:
        if radius_nm is not None:
            radius_value = float(str(radius_nm).strip())
            if radius_value <= 0:
                radius_value = None
    except Exception:
        radius_value = None

    if isinstance(coords, list) and coords:
        logger.info("Rendering polygon with %d points on map", len(coords))
        import math
        lats = [p[0] for p in coords]
        lons = [p[1] for p in coords]
        min_lat, max_lat = min(lats), max(lats)
        min_lon, max_lon = min(lons), max(lons)
        lat_pad = max((max_lat - min_lat) * 0.1, 0.1)
        lon_pad = max((max_lon - min_lon) * 0.1, 0.1)
        # Adjust extent so the geographic box matches the image aspect ratio
        map_w, map_h = size
        desired_ratio = float(map_w) / float(map_h)
        lat_span = max(max_lat - min_lat, 1e-6)
        lon_span = max(max_lon - min_lon, 1e-6)
        center_lat = (max_lat + min_lat) / 2.0
        cos_lat = max(math.cos(math.radians(center_lat)), 1e-6)
        # approximate longitudinal span in latitude-equivalent units
        adj_lon_span = lon_span * cos_lat
        current_ratio = adj_lon_span / lat_span
        if current_ratio < desired_ratio:
            # need wider longitudinal span
            needed_adj_lon = desired_ratio * lat_span
            needed_lon_span = needed_adj_lon / cos_lat
            extra = (needed_lon_span - lon_span) / 2.0
            min_lon -= extra
            max_lon += extra
        elif current_ratio > desired_ratio:
            # need taller latitudinal span
            needed_lat_span = adj_lon_span / desired_ratio
            extra = (needed_lat_span - lat_span) / 2.0
            min_lat -= extra
            max_lat += extra
        extent = [min_lon - lon_pad, max_lon + lon_pad, min_lat - lat_pad, max_lat + lat_pad]
        # Apply global extent scale so the mapped area is slightly larger (zoom out).
        try:
            center_lon = (extent[0] + extent[1]) / 2.0
            center_lat = (extent[2] + extent[3]) / 2.0
            half_lon = (extent[1] - extent[0]) / 2.0
            half_lat = (extent[3] - extent[2]) / 2.0
            half_lon *= MAP_EXTENT_SCALE
            half_lat *= MAP_EXTENT_SCALE
            extent = [center_lon - half_lon, center_lon + half_lon, center_lat - half_lat, center_lat + half_lat]
        except Exception:
            pass
    elif isinstance(coords, tuple) and coords:
        logger.info("Rendering single point on map at lat=%.4f, lon=%.4f", coords[0], coords[1])
        import math
        lat, lon = coords
        if radius_value is not None:
            base_half_lat = max(radius_value / 60.0, 0.15)
            cos_lat = max(math.cos(math.radians(lat)), 1e-6)
            base_half_lon = max(radius_value / (60.0 * cos_lat), 0.15)
        else:
            # base half-spans (degrees)
            base_half_lat = 1.0
            base_half_lon = 1.0
        map_w, map_h = size
        desired_ratio = float(map_w) / float(map_h)
        center_lat = lat
        cos_lat = max(math.cos(math.radians(center_lat)), 1e-6)
        adj_lon_span = (base_half_lon * 2.0) * cos_lat
        lat_span = (base_half_lat * 2.0)
        current_ratio = adj_lon_span / lat_span if lat_span > 0 else 1.0
        if current_ratio < desired_ratio:
            needed_adj_lon = desired_ratio * lat_span
            needed_lon_span = needed_adj_lon / cos_lat
            half_lon = needed_lon_span / 2.0
            half_lat = base_half_lat
        else:
            needed_lat_span = adj_lon_span / desired_ratio
            half_lat = needed_lat_span / 2.0
            half_lon = base_half_lon
        # Scale halves slightly so the point area appears smaller on the map (zoom out)
        try:
            half_lon *= MAP_EXTENT_SCALE
            half_lat *= MAP_EXTENT_SCALE
        except Exception:
            pass
        extent = [lon - half_lon, lon + half_lon, lat - half_lat, lat + half_lat]
    else:
        logger.info("No valid coordinates provided, using default global extent")
        extent = [-180, 180, -90, 90]

    ax.set_extent(extent, crs=ccrs.PlateCarree())

    # Add simple cartographic features with dark theme
    try:
        # Use requested ocean and land colors: ocean=#262626, land=#090909
        ax.add_feature(cfeature.OCEAN.with_scale('50m'), facecolor='#262626')
        # Render inland lakes using the same ocean color to match dark theme
        ax.add_feature(cfeature.LAKES.with_scale('50m'), facecolor='#262626')
        ax.add_feature(cfeature.LAND.with_scale('50m'), facecolor='#090909')
        ax.add_feature(cfeature.COASTLINE.with_scale('50m'), edgecolor='#2b2b2b', linewidth=0.5)
        # Draw province (admin-1) and country (admin-0) boundaries.
        # Countries are drawn thicker than provinces to improve readability.
        try:
            admin0 = cfeature.NaturalEarthFeature(category='cultural', name='admin_0_boundary_lines_land', scale='50m', facecolor='none')
            ax.add_feature(admin0, edgecolor='#3b3b3b', linewidth=1.2, zorder=7)
        except Exception:
            # If NaturalEarth admin layers aren't available, fall back to BORDERS
            ax.add_feature(cfeature.BORDERS.with_scale('50m'), edgecolor='#3b3b3b', linewidth=1.0)
    except Exception:
        # some cartopy installations may not have naturalearth data available; fall back to coastlines and lakes if possible
        ax.coastlines(resolution='110m', color='#2b2b2b', linewidth=0.5)
        try:
            ax.add_feature(cfeature.LAKES.with_scale('110m'), facecolor='#262626')
        except Exception:
            pass

    # Label visible countries and large named geographic features (islands, peninsulas)
    try:
        # imports localized so failure here doesn't break map drawing
        from cartopy.io import shapereader
        import matplotlib.patheffects as patheffects
        import matplotlib.font_manager as fm
        # choose a label color lighter than the ocean (#262626 -> #858585)
        label_color = "#858585"
        # prefer JetBrains Mono bundled in project's fonts/ directory when available
        jet_font_path = None
        project_fonts = Path(__file__).parent / "fonts"
        if project_fonts.exists():
            for f in project_fonts.glob("*.ttf"):
                fn = f.name.lower()
                if 'jetbrains' in fn or 'jetbrainsmono' in fn or 'jetbrains-mono' in fn:
                    jet_font_path = str(f)
                    break

        # Precompute extent and margins used by multiple labelers
        ext_min_lon, ext_max_lon, ext_min_lat, ext_max_lat = extent[0], extent[1], extent[2], extent[3]
        ext_lon_span = max(ext_max_lon - ext_min_lon, 1e-6)
        ext_lat_span = max(ext_max_lat - ext_min_lat, 1e-6)
        margin_factor = 0.03
        lon_margin = ext_lon_span * margin_factor
        lat_margin = ext_lat_span * margin_factor

        # Helper: label countries from Natural Earth admin_0_countries
        try:
            countries_shp = shapereader.natural_earth(resolution='50m', category='cultural', name='admin_0_countries')
            reader = shapereader.Reader(countries_shp)
            # extent = [min_lon, max_lon, min_lat, max_lat]
            ext_min_lon, ext_max_lon, ext_min_lat, ext_max_lat = extent[0], extent[1], extent[2], extent[3]
            ext_lon_span = max(ext_max_lon - ext_min_lon, 1e-6)
            ext_lat_span = max(ext_max_lat - ext_min_lat, 1e-6)
            # small margin so labels don't sit right on the border
            margin_factor = 0.03
            lon_margin = ext_lon_span * margin_factor
            lat_margin = ext_lat_span * margin_factor
            for rec in reader.records():
                try:
                    attrs = rec.attributes
                    name = attrs.get('ADMIN') or attrs.get('NAME') or attrs.get('NAME_LONG') or attrs.get('SOVEREIGNT')
                    if not name:
                        continue
                    geom = rec.geometry
                    if geom is None:
                        continue
                    minx, miny, maxx, maxy = geom.bounds
                    # quick intersection test against current extent
                    if maxx < ext_min_lon or minx > ext_max_lon or maxy < ext_min_lat or miny > ext_max_lat:
                        continue
                    # approximate pixel span of this feature within current extent
                    pixel_w = (maxx - minx) / ext_lon_span * size[0]
                    pixel_h = (maxy - miny) / ext_lat_span * size[1]
                    maxpix = max(pixel_w, pixel_h)
                    # skip small countries to avoid clutter; threshold tuned for readability
                    if maxpix < 60:
                        continue
                    # choose a point guaranteed to lie within the geometry for label placement
                    try:
                        label_pt = geom.representative_point()
                    except Exception:
                        label_pt = geom.centroid
                    lx, ly = label_pt.x, label_pt.y
                    # ensure label point is comfortably inside the visible extent
                    if not (ext_min_lon + lon_margin <= lx <= ext_max_lon - lon_margin and ext_min_lat + lat_margin <= ly <= ext_max_lat - lat_margin):
                        continue
                    # slightly reduce label size for readability and compactness
                    fontsize = max(7, min(12, int(maxpix / 18)))
                    if jet_font_path:
                        font_prop = fm.FontProperties(fname=jet_font_path, size=fontsize)
                    else:
                        font_prop = fm.FontProperties(family='monospace', size=fontsize)
                    txt = ax.text(lx, ly, name, fontproperties=font_prop, fontweight='bold', color=label_color, transform=ccrs.PlateCarree(), ha='center', va='center', zorder=11, clip_on=True)
                    txt.set_path_effects([patheffects.withStroke(linewidth=2, foreground='black')])
                    try:
                        txt.set_clip_path(ax.patch)
                    except Exception:
                        pass
                except Exception:
                    # continue labeling other features even if one fails
                    continue
        except Exception:
            logger.exception("Failed to load admin_0_countries shapefile for labeling")

        # Label visible large water bodies (oceans, named lakes) using physical layers
        try:
            water_candidates = [
                ('ocean', 'physical', '50m'),
                ('lakes', 'physical', '50m'),
                ('ocean', 'physical', '10m'),
                ('lakes', 'physical', '10m'),
            ]
            for name, category, res in water_candidates:
                try:
                    path = shapereader.natural_earth(resolution=res, category=category, name=name)
                    wreader = shapereader.Reader(path)
                except Exception:
                    wreader = None
                if not wreader:
                    continue
                for wrec in wreader.records():
                    try:
                        wattr = wrec.attributes
                        # common name keys
                        wname = (wattr.get('name') or wattr.get('NAME') or wattr.get('NAME_EN') or wattr.get('NAME_LONG') or wattr.get('NAME_HI') or '')
                        if not wname:
                            continue
                        wgeom = wrec.geometry
                        if wgeom is None:
                            continue
                        minx, miny, maxx, maxy = wgeom.bounds
                        # quick intersection test
                        if maxx < ext_min_lon or minx > ext_max_lon or maxy < ext_min_lat or miny > ext_max_lat:
                            continue
                        pixel_w = (maxx - minx) / ext_lon_span * size[0]
                        pixel_h = (maxy - miny) / ext_lat_span * size[1]
                        maxpix = max(pixel_w, pixel_h)
                        # only label sufficiently large water bodies
                        if maxpix < 60:
                            continue
                        try:
                            wlabel_pt = wgeom.representative_point()
                        except Exception:
                            wlabel_pt = wgeom.centroid
                        wx, wy = wlabel_pt.x, wlabel_pt.y
                        if not (ext_min_lon + lon_margin <= wx <= ext_max_lon - lon_margin and ext_min_lat + lat_margin <= wy <= ext_max_lat - lat_margin):
                            continue
                        # fontsize tuned to feature size
                        wfontsize = max(8, min(18, int(maxpix / 22)))
                        if jet_font_path:
                            wfont_prop = fm.FontProperties(fname=jet_font_path, size=wfontsize)
                        else:
                            wfont_prop = fm.FontProperties(family='monospace', size=wfontsize)
                        wtxt = ax.text(wx, wy, wname, fontproperties=wfont_prop, color=label_color, transform=ccrs.PlateCarree(), ha='center', va='center', zorder=10, clip_on=True)
                        wtxt.set_path_effects([patheffects.withStroke(linewidth=2, foreground='black')])
                        try:
                            wtxt.set_clip_path(ax.patch)
                        except Exception:
                            pass
                    except Exception:
                        continue
        except Exception:
            logger.debug("Water-body labeling failed or not available")

        # Try to label named geographic features (islands, peninsulas) from available geographic names
        try:
            geo_reader = None
            for candidate in ('geographic_names', 'ne_10m_geographic_names', '10m_geographic_names'):
                try:
                    path = shapereader.natural_earth(resolution='10m', category='cultural', name=candidate)
                    geo_reader = shapereader.Reader(path)
                    break
                except Exception:
                    geo_reader = None
            if geo_reader:
                # reuse label margins
                for rec in geo_reader.records():
                    try:
                        attrs = rec.attributes
                        fname = (attrs.get('NAME') or attrs.get('name') or attrs.get('NAME_EN') or attrs.get('NAME_LONG') or '')
                        featclass = (attrs.get('FEATURECLA') or attrs.get('featurecla') or '')
                        if not fname:
                            continue
                        lower_n = str(fname).lower()
                        lower_fc = str(featclass).lower()
                        if 'island' not in lower_n and 'island' not in lower_fc and 'isle' not in lower_n and 'peninsula' not in lower_n and 'peninsula' not in lower_fc:
                            continue
                        geom = rec.geometry
                        if geom is None:
                            continue
                        minx, miny, maxx, maxy = geom.bounds
                        if maxx < ext_min_lon or minx > ext_max_lon or maxy < ext_min_lat or miny > ext_max_lat:
                            continue
                        pixel_w = (maxx - minx) / ext_lon_span * size[0]
                        pixel_h = (maxy - miny) / ext_lat_span * size[1]
                        maxpix = max(pixel_w, pixel_h)
                        # allow slightly smaller threshold for named features
                        if maxpix < 30:
                            continue
                        try:
                            label_pt = geom.representative_point()
                        except Exception:
                            label_pt = geom.centroid
                        lx, ly = label_pt.x, label_pt.y
                        # ensure label point is inside visible area with margin
                        if not (ext_min_lon + lon_margin <= lx <= ext_max_lon - lon_margin and ext_min_lat + lat_margin <= ly <= ext_max_lat - lat_margin):
                            continue
                        # reduce feature label size slightly
                        fontsize = max(6, min(10, int(maxpix / 24)))
                        if jet_font_path:
                            font_prop = fm.FontProperties(fname=jet_font_path, size=fontsize)
                        else:
                            font_prop = fm.FontProperties(family='monospace', size=fontsize)
                        txt = ax.text(lx, ly, fname, fontproperties=font_prop, fontsize=fontsize, color=label_color, transform=ccrs.PlateCarree(), ha='center', va='center', zorder=11, clip_on=True)
                        txt.set_path_effects([patheffects.withStroke(linewidth=1.8, foreground='black')])
                        try:
                            txt.set_clip_path(ax.patch)
                        except Exception:
                            pass
                    except Exception:
                        continue
        except Exception:
            logger.debug("No geographic-names layer available or labeling failed")

        # Draw Starbase, TX marker and label if visible
        try:
            star_lat = 25.9896
            star_lon = -97.1849
            if ext_min_lon <= star_lon <= ext_max_lon and ext_min_lat <= star_lat <= ext_max_lat:
                # marker
                try:
                    ax.scatter([star_lon], [star_lat], s=70, color='#FF8014', edgecolors='black', linewidths=0.8, transform=ccrs.PlateCarree(), zorder=13)
                except Exception:
                    try:
                        ax.plot(star_lon, star_lat, marker='o', markersize=6, color='#FF8014', transform=ccrs.PlateCarree(), zorder=13)
                    except Exception:
                        pass
                # label offset a bit to the right and up
                try:
                    dx = ext_lon_span * 0.02
                    dy = ext_lat_span * 0.01
                    sname = 'Starbase, TX'
                    sfontsize = max(8, min(12, int(min(size) / 60)))
                    if jet_font_path:
                        sfont_prop = fm.FontProperties(fname=jet_font_path, size=sfontsize)
                    else:
                        sfont_prop = fm.FontProperties(family='monospace', size=sfontsize)
                    stxt = ax.text(star_lon + dx, star_lat + dy, sname, fontproperties=sfont_prop, color=label_color, transform=ccrs.PlateCarree(), ha='left', va='bottom', zorder=13, clip_on=True)
                    stxt.set_path_effects([patheffects.withStroke(linewidth=1.8, foreground='black')])
                    try:
                        stxt.set_clip_path(ax.patch)
                    except Exception:
                        pass
                except Exception:
                    pass
        except Exception:
            logger.debug('Starbase marker placement failed')

    except Exception:
        # drawing labels is non-critical; do not fail the whole rendering if shapereader/patheffects unavailable
        logger.debug("Shapereader or patheffects not available; skipping labels")
    # Draw polygon, circle, or point
    if isinstance(coords, list) and coords:
        poly_coords = [(lon, lat) for lat, lon in coords]
        try:
            poly = Polygon(poly_coords)
            logger.info("Drawing polygon on cartopy map")
            ax.add_geometries([poly], crs=ccrs.PlateCarree(), facecolor=(207/255, 0, 0, 0.18), edgecolor=(207/255, 0, 0, 0.95), linewidth=1.6)
        except Exception:
            logger.exception("Failed to draw polygon on cartopy map")
    elif isinstance(coords, tuple) and coords:
        lat, lon = coords
        if radius_value is not None:
            import math
            logger.info("Drawing circle on cartopy map with radius %.2f NM", radius_value)
            circle_pts = []
            lat_deg = radius_value / 60.0
            cos_lat = max(math.cos(math.radians(lat)), 1e-6)
            lon_deg = radius_value / (60.0 * cos_lat)
            for i in range(72):
                ang = 2.0 * math.pi * (i / 72.0)
                p_lat = lat + lat_deg * math.sin(ang)
                p_lon = lon + lon_deg * math.cos(ang)
                circle_pts.append((p_lon, p_lat))
            try:
                circle = Polygon(circle_pts)
                ax.add_geometries([circle], crs=ccrs.PlateCarree(), facecolor=(207/255, 0, 0, 0.18), edgecolor=(207/255, 0, 0, 0.95), linewidth=1.6)
            except Exception:
                logger.exception("Failed to draw circle geometry on cartopy map")
        else:
            logger.info("Drawing point on cartopy map")
            # Intentionally do not draw a center marker or coordinate label per request

    # remove axes and padding
    ax.set_xticks([])
    ax.set_yticks([])
    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)

    # Force the GeoAxes to cover the entire figure area so the saved
    # PNG occupies the full requested pixel rectangle. Save with an
    # opaque facecolor so there aren't transparent bands at the top/bottom.
    try:
        ax.set_position([0, 0, 1, 1])
    except Exception:
        logger.exception("Failed to set axes position, map may have unexpected padding")

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=fig_dpi, facecolor=fig.get_facecolor(), transparent=False)
    plt.close(fig)
    buf.seek(0)
    map_img = Image.open(buf).convert('RGBA')
    # ensure exact size
    if map_img.size != size:
        map_img = map_img.resize(size, Image.LANCZOS)
    return map_img


def render_notam_image(notam: dict, out_path: str = "notam_sample.png"):
    logger.info("Rendering NOTAM image for %s", notam.get("number"))
    img = Image.new("RGBA", (CANVAS_W, CANVAS_H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Layout: right map box positioned with PADDING from right and top
    map_x = CANVAS_W - PADDING - MAP_W
    map_y = PADDING

    # Left column area
    left_x = PADDING
    left_y = PADDING + 50
    left_w = min(LEFT_MAX_W, map_x - PADDING - left_x)

    # Load fonts
    title_font = load_font("JetBrainsMono-Bold.ttf", 48)
    number_font = load_font("JetBrainsMono-Bold.ttf", 48)
    details_font = load_font("JetBrainsMono-Regular.ttf", 36)
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
    left_y += 14 + 32

    # NOTAM number
    draw.text((left_x, left_y), notam.get("number", ""), font=number_font, fill=RED_CF)
    left_y += 48 + 48

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
        left_y += 36 + 6

    left_y += 24
    
    # Times (Начало / Завершение) — compute a consistent value column so
    # the time values align with each other. Prefer right-aligned against
    # the left column's right edge; if space is insufficient, left-align
    # the values after the widest label so they still share the same x.
    time_label_font = load_font("JetBrainsMono-Bold.ttf", 24)
    time_value_font = load_font("JetBrainsMono-Regular.ttf", 24)
    time_label_color = WHITE
    time_value_color = (255, 128, 20)  # #FF8014
    time_gap = 8

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
    
    left_y += 24

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
    # Draw coords text centered
    coords = notam.get("coords")
    radius_nm = notam.get("radius_nm")

    # Try rendering a proper Earth map with the polygon/point using Cartopy
    try:
        map_img = render_map_image(coords, (MAP_W, MAP_H), radius_nm=radius_nm)
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


    img.save(out_path)
    logger.info("Saved NOTAM image to %s", out_path)
    return out_path

def main():
    # 1) Simple point NOTAM (decimal coordinates)
    notam_point = {
        "number": "TEST/001",
        "details": "TEST NOTAM POINT AREA",
        "coords": (52.5200, 13.4050),  # Berlin
        "meta": "(TEST FLIGHT OPS)",
        "author": "@test",
        "start": "23.06.2026, 10:00 UTC",
        "end": "23.06.2026, 12:00 UTC",
        "zone": "EDXX",
        "top": "FL999"
    }

    out1 = render_notam_image(notam_point, out_path="notam_test_point.png")
    print(f"[OK] Point NOTAM rendered: {out1}")

    # 2) Polygon NOTAM (rough box over Germany)
    notam_poly = {
        "number": "TEST/002",
        "details": "RESTRICTED AIRSPACE ACTIVITY",
        "coords": [
            (53.0, 12.0),
            (53.0, 14.0),
            (51.0, 14.0),
            (51.0, 12.0),
        ],
        "meta": "(TEST AIRSPACE)",
        "author": "@test",
        "start": "23.06.2026, 08:00 UTC",
        "end": "23.06.2026, 18:00 UTC",
        "zone": "EDYY",
        "top": "600"
    }

    out2 = render_notam_image(notam_poly, out_path="notam_test_polygon.png")
    print(f"[OK] Polygon NOTAM rendered: {out2}")

    # 3) Starship-style NOTAM (tests extract_starship_template + labeling logic)
    notam_starship = {
        "number": "TEST/003",
        "details": 
            extract_starship_template("SPACEX STARSHIP FLT-12 ASCENT REENTRY DEBRIS RESPONSE AREA TEMPORARY DANGER AREAS DUE TO LAUNCH OF THE SYSTEM")
        ,
        "coords": [
            (25.0, -97.0),
            (30.0, -90.0),
            (28.0, -85.0),
        ],
        "meta": "(SPACE OPS)",
        "author": "@spacex",
        "start": "23.06.2026, 14:00 UTC",
        "end": "23.06.2026, 16:00 UTC",
        "zone": "KZHU",
        "top": "999"
    }

    out3 = render_notam_image(notam_starship, out_path="notam_test_starship.png")
    print(f"[OK] Starship NOTAM rendered: {out3}")

    print("\nAll test images generated successfully.")


if __name__ == "__main__":
    main()