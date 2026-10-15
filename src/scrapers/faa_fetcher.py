"""HTTP-based FAA advisory fetching.

This module fetches the FAA System Operations advisory page over HTTP and
delegates parsing of the returned HTML to
:func:`src.parsers.faa_parser.parse_faa_advisory_html`.

The fetcher performs no persistence: it returns the parsed results to the
caller and returns an empty list on failure (see
:class:`~src.scrapers.http_fetcher.HttpFetcher`).
"""

from src.core.logging import logger
from src.parsers.faa_parser import parse_faa_advisory_html
from src.scrapers.http_fetcher import HttpFetcher

# FAA System Operations special-use advisory page.
FAA_ADVISORY_URL = "https://www.fly.faa.gov/adv/adv_spt"


class FaaAdvisoryFetcher(HttpFetcher):
    """FAA System Operations advisory page -> list of planned launches."""

    name = "FAA advisory"
    url = FAA_ADVISORY_URL

    def parse(self, text: str) -> list[dict]:
        return parse_faa_advisory_html(text)

    def failure(self) -> list[dict]:
        return []

    def describe(self, result: list[dict]) -> str:
        return f"{len(result)} launch(es)"


faa_advisory_fetcher = FaaAdvisoryFetcher()


if __name__ == "__main__":
    activities = faa_advisory_fetcher.fetch()
    logger.info(f"Total FAA activities fetched: {len(activities)}")
