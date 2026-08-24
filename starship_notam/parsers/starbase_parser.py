"""Starbase beach and road closure HTML parsing.

Pure-function parser: accepts raw HTML, returns structured data.
No I/O, no logging, no network imports.

Public API:
    parse_starbase_html(html: str) -> dict
"""

import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

CENTRAL = ZoneInfo("America/Chicago")
UTC = ZoneInfo("UTC")

TZ_SUFFIX_RE = re.compile(r"\bC\.?\s*T\.?\b", re.IGNORECASE)
DATE_RANGE_RE = re.compile(
    r"^(?P<start_month>[A-Za-z]+)\s+(?P<start_day>\d{1,2})(?:,\s*(?P<start_year>\d{4}))?(?:\s+from)?\s+(?P<start_time>\d{1,2}:\d{2}\s*[AP]M)\s+to\s+(?:(?P<end_month>[A-Za-z]+)\s+(?P<end_day>\d{1,2})(?:,\s*(?P<end_year>\d{4}))?\s+)?(?P<end_time>\d{1,2}:\d{2}\s*[AP]M)$",
    re.IGNORECASE,
)


def _normalize_date_text(date_str: str) -> str:
    """Remove timezone suffixes and collapse whitespace."""
    cleaned = TZ_SUFFIX_RE.sub("", date_str)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _normalize_time_text(time_text: str) -> str:
    """Ensure space between digits and AM/PM."""
    return re.sub(r"(\d)([AP]M)$", r"\1 \2", time_text.strip(), flags=re.IGNORECASE)


def parse_datetime_range(date_str: str, year: int | None = None) -> tuple[datetime, datetime]:
    """Parse a date range string into a (start_utc, end_utc) tuple.

    Interprets times as US Central and converts to UTC.
    Raises ValueError if the format is not recognized.
    """
    if not year:
        year = datetime.now().year

    normalized = _normalize_date_text(date_str)
    match = DATE_RANGE_RE.match(normalized)

    if not match:
        raise ValueError(f"Unrecognized closure date format: {date_str}")

    parts = match.groupdict()

    start_year = int(parts.get("start_year") or year)
    end_year = int(parts.get("end_year") or start_year)
    start_time = _normalize_time_text(parts["start_time"])
    end_time = _normalize_time_text(parts["end_time"])

    start = datetime.strptime(
        f"{parts['start_month']} {parts['start_day']} {start_year} {start_time}",
        "%B %d %Y %I:%M %p",
    ).replace(tzinfo=CENTRAL)

    end_month = parts.get("end_month") or parts["start_month"]
    end_day = parts.get("end_day") or parts["start_day"]

    end = datetime.strptime(
        f"{end_month} {end_day} {end_year} {end_time}",
        "%B %d %Y %I:%M %p",
    ).replace(tzinfo=CENTRAL)

    if not parts.get("end_month") and end < start:
        end = end + timedelta(days=1)

    return start.astimezone(UTC), end.astimezone(UTC)


def _extract_route(description: str | None) -> tuple[str | None, str | None]:
    """Extract origin/destination from a route description string."""
    if not description:
        return None, None

    match = re.search(r"\(from\s+(.+?)\s+to\s+(.+?)\)", description, re.IGNORECASE)
    if match:
        return match.group(1).strip(" ."), match.group(2).strip(" .")

    if " to " in description:
        origin, destination = [x.strip(" .") for x in description.split(" to ", 1)]
        if origin and destination:
            return origin, destination

    return None, None


def _is_notice_card(element: Any) -> bool:
    """Check if a BeautifulSoup element is a notice card."""
    if element is None:
        return False

    if element.get("id") == "rich-notification":
        return True

    return (
        element.find("h3") is not None
        or element.find(class_="closure-dates") is not None
    )


def _collect_notice_cards(container: Any) -> list:
    """Collect notice card elements from a container."""
    if container is None:
        return []

    cards = []
    seen: set[int] = set()

    if _is_notice_card(container):
        seen.add(id(container))
        cards.append(container)

    for element in container.select("#rich-notification"):
        if id(element) in seen:
            continue
        seen.add(id(element))
        cards.append(element)

    return cards


def parse_notice_container(container: Any, category: str | None = None) -> dict:
    """Parse a notice container element into a structured dict."""
    title = None
    title_el = container.select_one("h3, h4, .notice-title")
    if title_el:
        title = title_el.get_text(" ", strip=True)

    description = None
    description_el = container.select_one(
        ".w-richtext p, .w-richtext, .rich-text p, .rich-text"
    )
    if description_el:
        description = description_el.get_text(" ", strip=True)

    if not description:
        description = title

    periods: list[dict] = []
    closure_dates = container.select_one(".closure-dates")
    if closure_dates:
        label = None
        for child in closure_dates.find_all(recursive=False):
            classes = child.get("class") or []
            text = child.get_text(" ", strip=True)

            if not text:
                continue

            if "cms-big-text" in classes:
                label = text
                continue

            if "cms-small-text" in classes and label:
                period: dict[str, Any] = {
                    "label": label,
                    "raw_date": text,
                }
                try:
                    start_dt, end_dt = parse_datetime_range(text)
                    period["start_utc"] = start_dt.isoformat()
                    period["end_utc"] = end_dt.isoformat()
                except Exception:
                    pass  # Silently skip unparseable dates (pure parser, no logging)
                periods.append(period)
                label = None

    if category == "road":
        origin, destination = _extract_route(description)
    else:
        origin = destination = None

    primary = periods[0] if periods else {}

    return {
        "title": title,
        "description": description,
        "origin": origin,
        "destination": destination,
        "start_utc": primary.get("start_utc"),
        "end_utc": primary.get("end_utc"),
        "raw_date": primary.get("raw_date"),
        "periods": periods,
    }


def parse_rich_notification(notification: Any) -> list[dict]:
    """Parse a rich notification element into a list of event dicts."""
    text = notification.get_text("\n", strip=True)

    events: list[dict] = []
    current: dict[str, str] = {}

    for line in text.splitlines():
        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()

        if key == "description":
            if current:
                events.append(current)
            current = {"description": value}
        elif key == "date":
            current["date"] = value
        else:
            current[key] = value

    if current:
        events.append(current)

    parsed_events: list[dict] = []

    for event in events:
        description = event.get("description")
        date_raw = event.get("date")

        origin = destination = None
        if description and " to " in description:
            origin, destination = [x.strip() for x in description.split(" to ", 1)]
        elif description:
            origin = description

        start_utc = end_utc = None
        if date_raw:
            start_dt, end_dt = parse_datetime_range(date_raw)
            start_utc = start_dt.isoformat()
            end_utc = end_dt.isoformat()

        parsed_events.append({
            "description": description,
            "origin": origin,
            "destination": destination,
            "start_utc": start_utc,
            "end_utc": end_utc,
            "raw_date": date_raw,
        })

    return parsed_events


def parse_notice_card(card: Any, category: str | None = None) -> dict | None:
    """Dispatch to the correct parser for a notice card element."""
    if card.get("id") == "rich-notification":
        parsed = parse_rich_notification(card)
        if not parsed:
            return None

        first = parsed[0]
        if category == "road":
            origin, destination = _extract_route(first.get("description"))
            first["origin"] = origin
            first["destination"] = destination

        first.setdefault("periods", [dict(period) for period in parsed])
        first.setdefault("title", first.get("description"))
        return first

    return parse_notice_container(card, category=category)


def parse_starbase_html(html: str) -> dict:
    """Parse Starbase beach/road closure HTML into structured data.

    Args:
        html: Raw HTML string from the Starbase status page.

    Returns:
        Dictionary with keys:
            - "beach": dict | None — parsed beach closure info
            - "road_delays": list[dict] — parsed road delay entries
    """
    soup = BeautifulSoup(html, "html.parser")

    result: dict[str, Any] = {
        "beach": None,
        "road_delays": [],
    }

    # ---------------- BEACH ----------------
    beach_container = soup.select_one(
        ".beach-public-notice .notice-container, "
        ".beach-public-notice .notice-container-no-hover, "
        ".beach-updates, "
        ".notice-container-no-hover.beach-updates"
    )

    if beach_container:
        cards = _collect_notice_cards(beach_container)
        if cards:
            result["beach"] = parse_notice_card(cards[0], category="beach")

    # ---------------- ROADS ----------------
    road_container = soup.select_one("#road-closure, .road-updates")

    if road_container:
        cards = _collect_notice_cards(road_container)

        if cards:
            for card in cards:
                parsed = parse_notice_card(card, category="road")
                if parsed:
                    result["road_delays"].append(parsed)
        else:
            for item in soup.select("#road-closure .cms-item-2"):
                container = item.select_one(".notice-container-no-hover.road-updates")
                if not container:
                    continue

                empty = container.select_one(".empty-state")
                if empty and "w-condition-invisible" not in (empty.get("class") or []):
                    continue

                notif = container.select_one("#rich-notification")
                if not notif:
                    continue

                parsed = parse_notice_card(notif, category="road")
                if parsed:
                    result["road_delays"].append(parsed)

    return result
