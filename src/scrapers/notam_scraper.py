"""FAA NOTAM search over HTTP.

Runs a free-text search against the backend of the FAA NOTAM Search web app
(:data:`NOTAM_SEARCH_API_URL`), the same JSON endpoint the app renders its
results table from. Every NOTAM in the response already carries its full ICAO
text, so no per-row detail request is needed. Results come 30 to a page and
are followed via ``offset``.

The host sits behind Akamai, which rejects plain ``requests`` with ``403`` by
its TLS fingerprint, so the requests go through :mod:`curl_cffi` impersonating
Chrome. Parsing is delegated to
:func:`src.parsers.notam_search_parser.parse_notam_search_page`.

The scraper performs no persistence: it returns the results to the caller and
raises on failure.
"""

from curl_cffi import requests as cffi_requests

from src.core.logging import logger
from src.parsers.notam_search_parser import parse_notam_search_page

NOTAM_SEARCH_API_URL = "https://notams.aim.faa.gov/notamSearch/search"

# Free-text search, as picked in the app's Location dropdown.
_FREE_TEXT_SEARCH_TYPE = "4"

# Seconds before a page request is abandoned.
_TIMEOUT = 40

# Upper bound on pages followed per keyword, in case the API's counts misbehave.
_MAX_PAGES = 20


def _session():
    return cffi_requests.Session(impersonate="chrome")


def search_notams(keyword: str) -> list[dict]:
    """Search the FAA NOTAM site for ``keyword`` and return structured results.

    Each returned dict contains the keys: ``location``, ``number``, ``class``,
    ``start_date_utc``, ``end_date_utc``, ``condition`` and ``icao_message``
    (a string, which may be empty). This function does NOT persist any data.

    Raises:
        Exception: on a network error, an HTTP error status or an unreadable
            response.
    """
    with _session() as session:
        return _search(session, keyword)


def search_notams_many(keywords) -> dict[str, list[dict]]:
    """Run :func:`search_notams` for several keywords on one HTTP session.

    A failure for one keyword is logged and yields an empty list for it; the
    remaining keywords still run.
    """
    results: dict[str, list[dict]] = {}
    with _session() as session:
        for keyword in keywords:
            try:
                results[keyword] = _search(session, keyword)
            except Exception:
                logger.exception(f"NOTAM search failed for keyword: {keyword}")
                results[keyword] = []
    return results


def _search(session, keyword: str) -> list[dict]:
    """Fetch every page of one free-text search and return all rows."""
    logger.info(f"Searching NOTAMs for: {keyword}")
    data: list[dict] = []
    for _ in range(_MAX_PAGES):
        response = session.post(
            NOTAM_SEARCH_API_URL,
            data={
                "searchType": _FREE_TEXT_SEARCH_TYPE,
                "freeFormText": keyword,
                "notamsOnly": "false",
                "offset": str(len(data)),
            },
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        rows, total = parse_notam_search_page(response.text)
        data.extend(rows)
        if not rows or len(data) >= total:
            break
    else:
        logger.warning(f"NOTAM search for {keyword!r} stopped after {_MAX_PAGES} pages")
    logger.info(f"Found {len(data)} NOTAM(s) for {keyword!r}")
    return data


if __name__ == "__main__":
    notams = search_notams("STARSHIP")
    logger.info(f"Total NOTAMs extracted: {len(notams)}")
