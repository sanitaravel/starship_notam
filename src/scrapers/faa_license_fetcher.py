"""HTTP-based FAA DRS launch-license summary fetcher.

This module tracks a single FAA Dynamic Regulatory System (DRS) document -- the
Starship / Super Heavy Vehicle Operator License -- by reading its "Document
Details" metadata from the DRS JSON summary API
(``/api/browse/documents/summaryguiddocview/<DRSDOCID>``).

The API answers ``403`` without a session token. The DRS web app gets one as a
guest: ``/guest/login`` redirects back to the app and sets ``jwt`` and ``user``
cookies, which the app then sends as request headers of the same names. We do
the same with a :class:`requests.Session`.

The scraper performs no persistence: it returns a single normalized record dict
(or ``None``) to the caller and is fail-safe -- it returns ``None`` and never
raises on any request failure. Parsing/normalization is delegated to the pure
function in :mod:`src.parsers.faa_license_parser`.
"""

import requests

from src.core import config
from src.core.logging import logger
from src.parsers.faa_license_parser import parse_faa_license_summary

# Seconds before each request is abandoned.
_TIMEOUT = 30

# The DRS edge rejects requests without a browser-like User-Agent.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)


def fetch_faa_license() -> dict | None:
    """Fetch and normalize the tracked FAA DRS launch-license summary.

    Returns
    -------
    dict or None
        The normalized record produced by
        :func:`parse_faa_license_summary` (see that function for the shape), or
        ``None`` when the license could not be fetched/parsed for any reason.
        Never raises to the caller. Performs no database writes.
    """
    try:
        with requests.Session() as session:
            session.headers["User-Agent"] = _USER_AGENT
            payload = _fetch_summary(session)
    except Exception as e:
        logger.error(f"FAA DRS license fetch failed: {e}")
        return None

    record = parse_faa_license_summary(payload)
    if not record:
        logger.error(
            "FAA DRS license summary parsed to an empty record; discarding"
        )
        return None

    logger.info(
        "Fetched FAA DRS license '%s' (status=%r, revision=%r)",
        record.get("doc_number"),
        record.get("status"),
        record.get("revision_number"),
    )
    return record


def _fetch_summary(session: requests.Session) -> dict:
    """Log in as a guest, then GET the summary JSON with the guest token."""
    logger.info("Logging in to FAA DRS as a guest")
    session.get(
        config.FAA_LICENSE_GUEST_LOGIN_URL, allow_redirects=False, timeout=_TIMEOUT
    ).raise_for_status()
    token = session.cookies.get("jwt")
    if not token:
        raise RuntimeError("DRS guest login set no jwt cookie")

    summary_url = config.FAA_LICENSE_SUMMARY_URL
    logger.info("Fetching FAA DRS license summary JSON: %s", summary_url)
    response = session.get(
        summary_url,
        headers={
            "Accept": "application/json",
            "jwt": token,
            "user": session.cookies.get("user", ""),
        },
        timeout=_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    result = fetch_faa_license()
    logger.info(f"FAA DRS license record: {result}")
