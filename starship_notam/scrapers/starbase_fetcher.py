"""HTTP-based Starbase beach and road status fetching.

This module fetches the Starbase beach/road access status page over HTTP and
delegates parsing of the returned HTML to
:func:`starship_notam.parsers.starbase_parser.parse_starbase_html`.

The fetcher performs no persistence: it returns the parsed results to the
caller and returns a shape-consistent empty structure on failure so that the
caller can detect and handle errors without special-casing missing keys.
"""

import requests

from starship_notam.core.logging import logger
from starship_notam.parsers.starbase_parser import parse_starbase_html

# Starbase beach and road access status page.
STARBASE_STATUS_URL = "https://www.starbase.texas.gov/beach-road-access"


def fetch_starbase_status() -> dict:
    """Fetch the Starbase status page and return parsed closure data.

    Performs an HTTP GET against :data:`STARBASE_STATUS_URL`, passes the
    returned HTML to :func:`parse_starbase_html`, and returns the parsed dict.
    The returned dict contains the keys ``beach`` (dict | None) and
    ``road_delays`` (list[dict]).

    This function does NOT persist any data to the database.

    Returns
    -------
    dict
        Parsed closure data with keys ``beach`` and ``road_delays``. On request
        failure, a shape-consistent empty structure
        (``{"beach": None, "road_delays": []}``) is returned so the caller can
        detect failure via an empty result.

    Raises
    ------
    requests.RequestException
        Propagated from the underlying HTTP request. Currently caught and
        logged so an empty structure is returned instead, allowing the caller
        to detect failure via an empty result.
    """
    logger.info("Fetching Starbase beach and road status from %s", STARBASE_STATUS_URL)

    try:
        html = requests.get(STARBASE_STATUS_URL, timeout=30).text
    except requests.RequestException:
        logger.exception(
            "Failed to fetch Starbase status from %s", STARBASE_STATUS_URL
        )
        return {"beach": None, "road_delays": []}

    result = parse_starbase_html(html)
    logger.info(
        "Parsed Starbase status: beach=%s, road_delays=%d",
        "present" if result.get("beach") else "none",
        len(result.get("road_delays", [])),
    )
    return result


if __name__ == "__main__":
    data = fetch_starbase_status()
    logger.info(
        f"Starbase status fetched: beach={'present' if data.get('beach') else 'none'}, "
        f"road_delays={len(data.get('road_delays', []))}"
    )
