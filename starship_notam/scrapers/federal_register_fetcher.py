"""HTTP-based Federal Register document fetching.

Queries the public Federal Register API for the newest FAA documents that
mention SpaceX (see :data:`core.config.FEDERAL_REGISTER_PARAMS`). The API
needs no key and answers with plain JSON, so no browser is needed. Parsing is
delegated to
:func:`starship_notam.parsers.federal_register_parser.parse_federal_register_documents`.

The fetcher performs no persistence and never raises: on failure it logs and
returns ``None`` so callers can tell "fetch failed" apart from "no documents".
"""

from starship_notam.core import config
from starship_notam.core.logging import logger
from starship_notam.parsers.federal_register_parser import (
    parse_federal_register_documents,
)
from starship_notam.scrapers.http_fetcher import HttpFetcher


class FederalRegisterFetcher(HttpFetcher):
    """Federal Register API search -> newest FAA documents mentioning SpaceX."""

    name = "Federal Register documents"
    headers = {"User-Agent": "Mozilla/5.0"}

    @property
    def url(self) -> str:
        return config.FEDERAL_REGISTER_API_URL

    def params(self) -> dict:
        return config.FEDERAL_REGISTER_PARAMS

    def parse(self, text: str) -> list[dict]:
        return parse_federal_register_documents(text)

    def failure(self) -> None:
        return None

    def describe(self, result: list[dict]) -> str:
        return f"{len(result)} document(s)"


def fetch_federal_register_documents() -> list[dict] | None:
    """Fetch the newest FAA Federal Register documents mentioning SpaceX.

    Returns
    -------
    list[dict] or None
        The parsed document records (newest first, see
        :func:`parse_federal_register_documents`), or ``None`` when the
        request failed.
    """
    return FederalRegisterFetcher().fetch()


if __name__ == "__main__":
    for d in fetch_federal_register_documents() or []:
        logger.info(f"Federal Register document: {d}")
