"""HTTP-based SEC EDGAR filing fetching.

Reads SpaceX's EDGAR submissions JSON (:data:`core.config.SEC_EDGAR_SUBMISSIONS_URL`),
which lists every recent filing in one response, and keeps the forms in
:data:`core.config.SEC_EDGAR_FORMS`. SEC needs no key but blocks requests
without a descriptive ``User-Agent``
(:data:`core.config.SEC_USER_AGENT`). Parsing is delegated to
:func:`src.parsers.sec_edgar_parser.parse_sec_edgar_filings`.

The fetcher performs no persistence and never raises: on failure it logs and
returns ``None`` so callers can tell "fetch failed" apart from "no filings".
"""

from src.core import config
from src.core.logging import logger
from src.parsers.sec_edgar_parser import parse_sec_edgar_filings
from src.scrapers.http_fetcher import HttpFetcher


class SecEdgarFetcher(HttpFetcher):
    """EDGAR submissions JSON -> SpaceX filings of the posted form types."""

    name = "SEC EDGAR filings"

    @property
    def headers(self) -> dict:
        return {"User-Agent": config.SEC_USER_AGENT}

    @property
    def url(self) -> str:
        return config.SEC_EDGAR_SUBMISSIONS_URL

    def parse(self, text: str) -> list[dict]:
        return parse_sec_edgar_filings(text, config.SEC_EDGAR_FORMS)

    def failure(self) -> None:
        return None

    def describe(self, result: list[dict]) -> str:
        return f"{len(result)} filing(s)"


sec_edgar_filings_fetcher = SecEdgarFetcher()


if __name__ == "__main__":
    for f in sec_edgar_filings_fetcher.fetch() or []:
        logger.info(f"SEC EDGAR filing: {f}")
