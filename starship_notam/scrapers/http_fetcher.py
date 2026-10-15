"""Base class for the plain-HTTP fetchers.

Every HTTP source is fetched the same way: GET the URL, treat a network error
or an HTTP error status as a failed fetch, otherwise hand the body to a pure
parser from :mod:`starship_notam.parsers`. Subclasses only describe the
source: its URL, request options, parser and what to return on failure.

Fetchers perform no persistence and never raise on a failed request: they log
the error and return :meth:`HttpFetcher.failure`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import requests

from starship_notam.core.logging import logger


class HttpFetcher(ABC):
    """Fetch one HTTP source and parse its response body."""

    #: Source name used in log lines, e.g. "FAA advisory".
    name: str

    #: Seconds before the request is abandoned.
    timeout: float = 30

    #: Extra request headers, if the source needs any.
    headers: dict | None = None

    @property
    @abstractmethod
    def url(self) -> str:
        """URL to GET. A property so config-driven URLs are read per fetch."""

    def params(self) -> dict | None:
        """Query parameters for the request; none by default."""
        return None

    @abstractmethod
    def parse(self, text: str):
        """Turn the response body into the fetcher's result."""

    @abstractmethod
    def failure(self):
        """Value returned when the request fails (a fresh object per call)."""

    def describe(self, result) -> str:
        """Short summary of a parsed result for the log."""
        return f"{len(result)} item(s)"

    def fetch(self):
        """GET :attr:`url` and return the parsed result, or :meth:`failure`."""
        url = self.url
        logger.info("Fetching %s from %s", self.name, url)
        try:
            response = requests.get(
                url, params=self.params(), headers=self.headers, timeout=self.timeout
            )
            response.raise_for_status()
        except requests.RequestException:
            logger.exception("Failed to fetch %s from %s", self.name, url)
            return self.failure()

        result = self.parse(response.text)
        logger.info("Parsed %s: %s", self.name, self.describe(result))
        return result
