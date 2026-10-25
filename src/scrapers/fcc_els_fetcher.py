"""HTTP-based FCC ELS (Experimental Licensing System) search.

This module submits the FCC ELS Generic Search form for SpaceX license
applications over a rolling one-month window, follows each result row's
"View Form -> Current" (``STA_Print.cfm``) detail link, and returns a list of
merged application dicts.

The FCC ELS site is a classic server-rendered ColdFusion (``.cfm``)
application, so each step is a single request; the heavy parsing is delegated
to the pure functions in :mod:`src.parsers.fcc_els_parser`. The host sits
behind Akamai, which rejects plain ``requests`` by its TLS fingerprint, so the
requests go through :mod:`curl_cffi` impersonating Chrome. The search form
must be loaded first: it sets the session cookie, and the results page answers
``503`` unless the POST carries every field of the form.

The scraper performs no persistence: it returns the scraped results to the
caller and is fail-safe (returns ``[]`` and never raises to the caller on any
request failure).
"""

import calendar
from datetime import date
from urllib.parse import urljoin

from curl_cffi import requests as cffi_requests

from src.core import config
from src.core.logging import logger
from src.parsers.fcc_els_parser import (
    parse_fcc_els_detail_html,
    parse_fcc_els_results_html,
    parse_fcc_els_search_form,
)

# --- Search form ---------------------------------------------------------
#
# The form on the FCC ELS Generic Search page (``GenericSearch.cfm``) is
# ``name="generic_search_form"`` and posts to ``GenericSearchResult.cfm``. We
# fill four of its fields and submit the rest at their defaults:
#
#   Applicant Name      -> name_licensee
#   Receipt Date (from) -> receipt_date_from
#   Receipt Date (to)   -> receipt_date_to
#   Records per page    -> show_records (defaults to "10")
_SEARCH_FORM_NAME = "generic_search_form"
_LICENSEE_FIELD_NAME = "name_licensee"
_RECEIPT_FROM_FIELD_NAME = "receipt_date_from"
_RECEIPT_TO_FIELD_NAME = "receipt_date_to"
_SHOW_RECORDS_FIELD_NAME = "show_records"

# Number of detail-page request attempts per result row.
_DETAIL_MAX_ATTEMPTS = 3

# Seconds before each request is abandoned.
_TIMEOUT = 30


def _receipt_date_to(today: date | None = None) -> str:
    """Return ``today`` formatted as ``mm/dd/yyyy``.

    Parameters
    ----------
    today : date, optional
        Reference date. Defaults to :func:`datetime.date.today`.
    """
    if today is None:
        today = date.today()
    return today.strftime("%m/%d/%Y")


def _receipt_date_from(today: date | None = None) -> str:
    """Return ``today`` minus one calendar month formatted as ``mm/dd/yyyy``.

    "One month earlier" is computed by decrementing the month (wrapping the year
    when the current month is January) and clamping the day to the last valid
    day of the target month (e.g. Mar 31 -> Feb 28/29).

    Parameters
    ----------
    today : date, optional
        Reference date. Defaults to :func:`datetime.date.today`.
    """
    if today is None:
        today = date.today()

    if today.month == 1:
        target_year = today.year - 1
        target_month = 12
    else:
        target_year = today.year
        target_month = today.month - 1

    target_day = min(today.day, calendar.monthrange(target_year, target_month)[1])
    return date(target_year, target_month, target_day).strftime("%m/%d/%Y")


def fetch_fcc_els_applications() -> list[dict]:
    """Search FCC ELS for SpaceX applications and return application dicts.

    Fail-safe: returns ``[]`` on any search failure and never raises to the
    caller. Performs no database writes.

    Each returned dict has the keys ``file_number``, ``application_seq``,
    ``applicant_name``, ``call_sign``, ``receipt_date``, ``status``,
    ``status_date``, ``current_detail_url``, and ``detail`` (a
    ``{label: value}`` dict, possibly empty).
    """
    results: list[dict] = []
    try:
        with cffi_requests.Session(impersonate="chrome") as session:
            rows = _search(session)
            if rows is None:
                return []
            for row in rows:
                app = _with_detail(session, row)
                if app is not None:
                    results.append(app)
    except Exception as e:
        # Any unexpected request failure is fail-safe: log and return whatever
        # was accumulated (never raise to the caller).
        logger.error(f"FCC ELS scrape failed: {e}")
    return results


def _search(session) -> list[dict] | None:
    """Load the search form, submit it and parse the results table."""
    search_url = config.FCC_ELS_SEARCH_URL
    logger.info(f"Opening FCC ELS search page: {search_url}")
    page = session.get(search_url, timeout=_TIMEOUT)
    page.raise_for_status()
    form = parse_fcc_els_search_form(page.text, _SEARCH_FORM_NAME)
    if form is None:
        logger.error("FCC ELS search page has no search form")
        return None
    action, fields = form

    receipt_from = _receipt_date_from()
    receipt_to = _receipt_date_to()
    logger.info(
        "Submitting FCC ELS search: licensee=%r, receipt_from=%s, "
        "receipt_to=%s, show_records=%s",
        config.FCC_ELS_SEARCH_TERM,
        receipt_from,
        receipt_to,
        config.FCC_ELS_RECORD_LIMIT,
    )
    fields.update({
        _LICENSEE_FIELD_NAME: config.FCC_ELS_SEARCH_TERM,
        _RECEIPT_FROM_FIELD_NAME: receipt_from,
        _RECEIPT_TO_FIELD_NAME: receipt_to,
        _SHOW_RECORDS_FIELD_NAME: str(config.FCC_ELS_RECORD_LIMIT),
    })
    response = session.post(
        urljoin(search_url, action),
        data=fields,
        headers={"Referer": search_url},
        timeout=_TIMEOUT,
    )
    response.raise_for_status()

    rows = parse_fcc_els_results_html(response.text)
    logger.info(f"Parsed {len(rows)} FCC ELS result row(s)")
    return rows


def _with_detail(session, row: dict) -> dict | None:
    """Fetch a result row's detail page and merge it in; ``None`` on failure."""
    file_number = row.get("file_number")
    # The parser returns the raw, root-relative href (e.g.
    # "/oetcf/els/reports/STA_Print.cfm?.."); resolve it against the search page.
    detail_url = urljoin(config.FCC_ELS_SEARCH_URL, row.get("current_detail_url"))
    detail: dict | None = None

    for attempt in range(1, _DETAIL_MAX_ATTEMPTS + 1):
        try:
            response = session.get(detail_url, timeout=_TIMEOUT)
            response.raise_for_status()
            detail = parse_fcc_els_detail_html(response.text)
            break
        except Exception as e:
            logger.info(
                "FCC ELS detail attempt %d/%d failed for file_number %r: %s",
                attempt,
                _DETAIL_MAX_ATTEMPTS,
                file_number,
                e,
            )

    if detail is None:
        # All retries exhausted (or a parse failure). Discard the partial data
        # for this row and continue with the next.
        logger.error(
            "Discarding FCC ELS application %r: failed to retrieve or parse "
            "detail page after %d attempts",
            file_number,
            _DETAIL_MAX_ATTEMPTS,
        )
        return None

    return {
        "file_number": row.get("file_number"),
        "application_seq": row.get("application_seq"),
        "applicant_name": row.get("applicant_name"),
        "call_sign": row.get("call_sign"),
        "receipt_date": row.get("receipt_date"),
        "status": row.get("status"),
        "status_date": row.get("status_date"),
        "current_detail_url": row.get("current_detail_url"),
        "detail": detail,
    }


if __name__ == "__main__":
    apps = fetch_fcc_els_applications()
    logger.info(f"Total FCC ELS applications extracted: {len(apps)}")
