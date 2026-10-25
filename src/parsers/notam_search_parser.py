"""FAA NOTAM Search JSON parsing.

Pure-function parser for one page of the FAA NOTAM Search backend
(``notamSearch/search``), the JSON the search web app renders its results
table from. It performs no network, database, or filesystem operations.

Public API:
    parse_notam_search_page(text: str) -> tuple[list[dict], int]
"""

from __future__ import annotations

import json

from src.core.logging import logger


def _text(value) -> str:
    """Strip a JSON value to text; the API pads empty fields with a space."""
    return str(value or "").strip()


def _row(notam: dict) -> dict:
    """One NOTAM -> the row dict the NOTAM orchestrator persists."""
    # International NOTAMs carry the ICAO form; domestic ones may only have
    # the traditional text. The API uses CRLF line endings.
    message = _text(notam.get("icaoMessage")) or _text(notam.get("traditionalMessage"))
    return {
        "location": _text(notam.get("facilityDesignator")),
        "number": _text(notam.get("notamNumber")),
        "class": _text(notam.get("featureName")),
        "start_date_utc": _text(notam.get("startDate")),
        "end_date_utc": _text(notam.get("endDate")),
        "condition": _text(notam.get("traditionalMessageFrom4thWord")),
        "icao_message": message.replace("\r\n", "\n"),
    }


def parse_notam_search_page(text: str) -> tuple[list[dict], int]:
    """Parse one search response into ``(rows, total)``.

    ``rows`` holds a dict per NOTAM on this page with the keys ``location``,
    ``number``, ``class``, ``start_date_utc``, ``end_date_utc``,
    ``condition`` and ``icao_message``; ``total`` is the number of NOTAMs the
    search matched across all pages.

    Raises:
        ValueError: if the body is not a search response, or the API reports
            an error.
    """
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"NOTAM search returned non-JSON: {e}") from e
    if not isinstance(payload, dict) or "notamList" not in payload:
        raise ValueError("NOTAM search response has no notamList")
    error = _text(payload.get("error"))
    if error:
        raise ValueError(f"NOTAM search reported an error: {error}")

    rows = [_row(n) for n in payload["notamList"] if isinstance(n, dict)]
    total = int(payload.get("totalNotamCount") or 0)
    logger.debug("Parsed %d NOTAM search row(s) of %d", len(rows), total)
    return rows, total
