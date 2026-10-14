"""Federal Register search-results parsing.

Pure-function parser for the JSON returned by the Federal Register documents
API (``/api/v1/documents.json``). The payload looks like::

    {"count": 66, "results": [{"document_number": "2026-20963",
                               "title": "...", "type": "Notice",
                               "abstract": "...", "publication_date": "2026-10-14",
                               "html_url": "...", "pdf_url": "...",
                               "comments_close_on": null}, ...]}

It performs no network, database, or filesystem operations.

Public API:
    parse_federal_register_documents(payload: dict | str) -> list[dict]
"""

from __future__ import annotations

import json
from typing import Any

from starship_notam.core.logging import logger


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def parse_federal_register_documents(payload: Any) -> list[dict]:
    """Normalize the search payload into a list of document records.

    Parameters
    ----------
    payload : dict or str
        The parsed JSON, or the raw JSON text.

    Returns
    -------
    list[dict]
        One record per document, in the order the server returned them
        (newest first), each with the keys ``document_number``, ``title``,
        ``doc_type``, ``abstract``, ``publication_date`` and
        ``comments_close_on`` (ISO dates, or ``""``), ``html_url`` and
        ``pdf_url``. Results without a ``document_number`` are dropped. A
        search with no matches has no ``results`` key and yields ``[]``, as
        does junk input.
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            logger.error("Federal Register response is not valid JSON")
            return []
    if not isinstance(payload, dict):
        logger.error("Federal Register response is not a JSON object")
        return []

    results = payload.get("results") or []
    if not isinstance(results, list):
        logger.error("Federal Register response has no 'results' list")
        return []

    records = []
    for row in results:
        if not isinstance(row, dict):
            continue
        document_number = _text(row.get("document_number"))
        if not document_number:
            logger.info("Skipping Federal Register result without document_number: %s", row)
            continue
        records.append(
            {
                "document_number": document_number,
                "title": _text(row.get("title")),
                "doc_type": _text(row.get("type")),
                "abstract": _text(row.get("abstract")),
                "publication_date": _text(row.get("publication_date")),
                "comments_close_on": _text(row.get("comments_close_on")),
                "html_url": _text(row.get("html_url")),
                "pdf_url": _text(row.get("pdf_url")),
            }
        )
    return records
