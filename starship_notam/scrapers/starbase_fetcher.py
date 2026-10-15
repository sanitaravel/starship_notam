"""HTTP-based Starbase beach and road status fetching.

This module fetches the Starbase beach/road access status page over HTTP and
delegates parsing of the returned HTML to
:func:`starship_notam.parsers.starbase_parser.parse_starbase_html`.

The fetcher performs no persistence: it returns the parsed results to the
caller and returns a shape-consistent empty structure on failure so that the
caller can detect and handle errors without special-casing missing keys.
"""

from starship_notam.core.logging import logger
from starship_notam.parsers.starbase_parser import parse_starbase_html
from starship_notam.scrapers.http_fetcher import HttpFetcher

# Starbase beach and road access status page.
STARBASE_STATUS_URL = "https://www.starbase.texas.gov/beach-road-access"


class StarbaseStatusFetcher(HttpFetcher):
    """Starbase beach/road access page -> beach closure and road delays."""

    name = "Starbase beach and road status"
    url = STARBASE_STATUS_URL

    def parse(self, text: str) -> dict:
        return parse_starbase_html(text)

    def failure(self) -> dict:
        return {"beach": None, "road_delays": []}

    def describe(self, result: dict) -> str:
        beach = "present" if result.get("beach") else "none"
        return f"beach={beach}, road_delays={len(result.get('road_delays', []))}"


def fetch_starbase_status() -> dict:
    """Fetch the Starbase status page and return parsed closure data.

    The returned dict contains the keys ``beach`` (dict | None) and
    ``road_delays`` (list[dict]). On request failure the same shape is
    returned empty (``{"beach": None, "road_delays": []}``). Does NOT persist
    any data to the database.
    """
    return StarbaseStatusFetcher().fetch()


if __name__ == "__main__":
    data = fetch_starbase_status()
    logger.info(
        f"Starbase status fetched: beach={'present' if data.get('beach') else 'none'}, "
        f"road_delays={len(data.get('road_delays', []))}"
    )
