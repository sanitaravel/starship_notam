"""HTTP-based FAA advisory fetching.

This module fetches the FAA System Operations advisory page over HTTP and
delegates parsing of the returned HTML to
:func:`starship_notam.parsers.faa_parser.parse_faa_advisory_html`.

The fetcher performs no persistence: it returns the parsed results to the
caller and either raises an exception or returns an empty list on failure so
that the caller can detect and handle errors.
"""

import requests

from starship_notam.core.logging import logger
from starship_notam.parsers.faa_parser import parse_faa_advisory_html

# FAA System Operations special-use advisory page.
FAA_ADVISORY_URL = "https://www.fly.faa.gov/adv/adv_spt"


def fetch_faa_advisory() -> list[dict]:
    """Fetch the FAA advisory page and return parsed launch dictionaries.

    Performs an HTTP GET against :data:`FAA_ADVISORY_URL`, passes the returned
    HTML to :func:`parse_faa_advisory_html`, and returns the parsed list. Each
    returned dict contains the keys ``mission`` (str), ``primary_window``
    (str | None), and ``backup_window`` (str | None).

    This function does NOT persist any data to the database.

    Returns
    -------
    list[dict]
        Parsed launch entries, or an empty list when the request fails.

    Raises
    ------
    requests.RequestException
        Propagated from the underlying HTTP request. Currently caught and
        logged so an empty list is returned instead, allowing the caller to
        detect failure via an empty result.
    """
    logger.info("Fetching FAA advisory from %s", FAA_ADVISORY_URL)

    try:
        html = requests.get(FAA_ADVISORY_URL, timeout=30).text
    except requests.RequestException:
        logger.exception("Failed to fetch FAA advisory from %s", FAA_ADVISORY_URL)
        return []

    launches = parse_faa_advisory_html(html)
    logger.info("Parsed %d launches from the FAA advisory", len(launches))
    return launches


if __name__ == "__main__":
    activities = fetch_faa_advisory()
    logger.info(f"Total FAA activities fetched: {len(activities)}")
