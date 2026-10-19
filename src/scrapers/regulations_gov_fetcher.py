"""HTTP-based Regulations.gov document fetching.

Searches the Regulations.gov v4 API for FAA and USCG documents matching each
of :data:`core.config.REGULATIONS_GOV_SEARCH_TERMS` (one fetcher per term;
:func:`fetch_regulations_gov_documents` merges them), and lists the files of a
single document. The API answers with JSON and needs an api.data.gov key
(:data:`core.config.REGULATIONS_GOV_API_KEY`), sent in the ``X-Api-Key``
header so it never shows up in a logged URL. Parsing is delegated to
:mod:`src.parsers.regulations_gov_parser`.

The fetchers perform no persistence and never raise: on failure they log and
return ``None`` so callers can tell "fetch failed" apart from "no documents".
"""

from __future__ import annotations

from src.core import config
from src.core.logging import logger
from src.parsers.regulations_gov_parser import (
    parse_regulations_gov_documents,
    parse_regulations_gov_files,
)
from src.scrapers.http_fetcher import HttpFetcher


class _RegulationsGovFetcher(HttpFetcher):
    """Shared request set-up: the API key header."""

    @property
    def headers(self) -> dict:
        return {"X-Api-Key": config.REGULATIONS_GOV_API_KEY}

    def failure(self) -> None:
        return None


class RegulationsGovSearch(_RegulationsGovFetcher):
    """Regulations.gov document search for one term -> newest FAA/USCG documents."""

    def __init__(self, term: str):
        self.term = term
        self.name = f"Regulations.gov documents matching {term!r}"

    @property
    def url(self) -> str:
        return f"{config.REGULATIONS_GOV_API_URL}/documents"

    def params(self) -> dict:
        return {**config.REGULATIONS_GOV_PARAMS, "filter[searchTerm]": self.term}

    def parse(self, text: str) -> list[dict]:
        return parse_regulations_gov_documents(text)

    def describe(self, result: list[dict]) -> str:
        return f"{len(result)} document(s)"


class RegulationsGovFiles(_RegulationsGovFetcher):
    """One Regulations.gov document with its attachments -> its downloadable files."""

    def __init__(self, document_id: str):
        self.document_id = document_id
        self.name = f"Regulations.gov files of {document_id}"

    @property
    def url(self) -> str:
        return f"{config.REGULATIONS_GOV_API_URL}/documents/{self.document_id}"

    def params(self) -> dict:
        return {"include": "attachments"}

    def parse(self, text: str) -> list[dict]:
        return parse_regulations_gov_files(text)

    def describe(self, result: list[dict]) -> str:
        return f"{len(result)} file(s)"


regulations_gov_searches = tuple(
    RegulationsGovSearch(term) for term in config.REGULATIONS_GOV_SEARCH_TERMS
)


def fetch_regulations_gov_documents() -> list[dict] | None:
    """Run every search and merge the results by document id.

    Returns the documents oldest first by posted date, or ``None`` if any
    search failed (a partial result would make a prefill miss documents).
    """
    merged: dict[str, dict] = {}
    for search in regulations_gov_searches:
        documents = search.fetch()
        if documents is None:
            return None
        for document in documents:
            merged.setdefault(document["document_id"], document)
    return sorted(merged.values(), key=lambda d: (d["posted_date"], d["document_id"]))


if __name__ == "__main__":
    for d in fetch_regulations_gov_documents() or []:
        logger.info(f"Regulations.gov document: {d}")
