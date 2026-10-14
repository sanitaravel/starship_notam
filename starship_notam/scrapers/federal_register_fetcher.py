"""HTTP-based Federal Register document fetching.

Queries the public Federal Register API for the newest FAA documents that
mention SpaceX (see :data:`core.config.FEDERAL_REGISTER_PARAMS`). The API
needs no key and answers with plain JSON, so no browser is needed. Parsing is
delegated to
:func:`starship_notam.parsers.federal_register_parser.parse_federal_register_documents`.

The fetcher performs no persistence and never raises: on failure it logs and
returns ``None`` so callers can tell "fetch failed" apart from "no documents".
"""

import requests

from starship_notam.core import config
from starship_notam.core.logging import logger
from starship_notam.parsers.federal_register_parser import (
    parse_federal_register_documents,
)


def fetch_federal_register_documents() -> list[dict] | None:
    """Fetch the newest FAA Federal Register documents mentioning SpaceX.

    Returns
    -------
    list[dict] or None
        The parsed document records (newest first, see
        :func:`parse_federal_register_documents`), or ``None`` when the
        request failed.
    """
    url = config.FEDERAL_REGISTER_API_URL
    logger.info("Fetching Federal Register documents from %s", url)
    try:
        response = requests.get(
            url,
            params=config.FEDERAL_REGISTER_PARAMS,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException:
        logger.exception("Failed to fetch Federal Register documents from %s", url)
        return None

    documents = parse_federal_register_documents(response.text)
    logger.info("Parsed %d Federal Register documents", len(documents))
    return documents


if __name__ == "__main__":
    for d in fetch_federal_register_documents() or []:
        logger.info(f"Federal Register document: {d}")
