"""Selenium-based FCC ELS (Experimental Licensing System) search automation.

This module drives the FCC ELS Generic Search web application to search for
SpaceX license applications over a rolling one-month window, follows each
result row's "View Form -> Current" (``STA_Print.cfm``) detail link, and
returns a list of merged application dicts.

Unlike the FAA NOTAM search (an Angular SPA), the FCC ELS site is a classic
server-rendered ColdFusion (``.cfm``) application: the results table and the
detail form are present in ``driver.page_source`` immediately after load, so
the heavy parsing is delegated to the pure functions in
:mod:`starship_notam.parsers.fcc_els_parser`.

The heavy Selenium dependency is imported lazily inside
:func:`fetch_fcc_els_applications` so that importing this module (and the
``scrapers`` package) does not require Selenium to be installed. This keeps the
scraper layer independently importable in test environments.

The scraper performs no persistence: it returns the scraped results to the
caller and is fail-safe (returns ``[]`` and never raises to the caller on any
search/navigation failure).
"""

import time
from datetime import date
from urllib.parse import urljoin

from starship_notam.core import config
from starship_notam.core.logging import logger
from starship_notam.scrapers.driver import create_driver
from starship_notam.parsers.fcc_els_parser import (
    parse_fcc_els_detail_html,
    parse_fcc_els_results_html,
)

# --- Form field locators -------------------------------------------------
#
# These identify the four search-form fields on the FCC ELS Generic Search
# page (``GenericSearch.cfm``). The names below were verified against the live
# page's HTML source: the form is ``name="generic_search_form"`` and posts to
# ``GenericSearchResult.cfm``.
#
#   Applicant Name      -> <input name="name_licensee">
#   Receipt Date (from) -> <input name="receipt_date_from">
#   Receipt Date (to)   -> <input name="receipt_date_to">
#   Records per page    -> <input name="show_records" value="10"> (a text input,
#                          NOT a <select>; defaults to "10")
#
# They are centralized here so they are easy to correct against the live page.
_LICENSEE_FIELD_NAME = "name_licensee"
_RECEIPT_FROM_FIELD_NAME = "receipt_date_from"
_RECEIPT_TO_FIELD_NAME = "receipt_date_to"
_SHOW_RECORDS_FIELD_NAME = "show_records"

# Locator used to detect that the results table has rendered after submitting
# the search. Best-effort; may need adjustment against the live page.
_RESULTS_TABLE_CSS = "table"

# Number of detail-page load attempts per result row.
_DETAIL_MAX_ATTEMPTS = 3

# Per-page load timeout (seconds) applied when fetching a detail page.
_PAGE_LOAD_TIMEOUT = 30


def _last_day_of_month(year: int, month: int) -> int:
    """Return the last valid day number for ``year``/``month``."""
    if month == 12:
        next_month_first = date(year + 1, 1, 1)
    else:
        next_month_first = date(year, month + 1, 1)
    # The day before the first of the following month is the last day.
    return (next_month_first.toordinal() - 1 - date(year, month, 1).toordinal()) + 1


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

    target_day = min(today.day, _last_day_of_month(target_year, target_month))
    return date(target_year, target_month, target_day).strftime("%m/%d/%Y")


def fetch_fcc_els_applications() -> list[dict]:
    """Search FCC ELS for SpaceX applications and return application dicts.

    Fail-safe: returns ``[]`` on any search/navigation failure and never raises
    to the caller. Closes the Selenium session in a ``finally`` block. Performs
    no database writes.

    Each returned dict has the keys ``file_number``, ``application_seq``,
    ``applicant_name``, ``call_sign``, ``receipt_date``, ``status``,
    ``status_date``, ``current_detail_url``, and ``detail`` (a
    ``{label: value}`` dict, possibly empty).
    """
    # Lazy imports -- selenium is an optional heavy dependency only needed at
    # call time, not at module import time (keeps the scrapers package
    # importable without selenium installed).
    try:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait
    except Exception as e:  # pragma: no cover - environment-dependent
        logger.error(f"Selenium is not available for FCC ELS scrape: {e}")
        return []

    driver = create_driver()

    results: list[dict] = []

    try:
        url = config.FCC_ELS_SEARCH_URL
        logger.info(f"Opening FCC ELS search page: {url}")
        driver.get(url)

        # --- Wait for the four search-form fields to be present -----------
        wait = WebDriverWait(driver, 30)
        try:
            licensee_field = wait.until(
                EC.presence_of_element_located((By.NAME, _LICENSEE_FIELD_NAME))
            )
            receipt_from_field = wait.until(
                EC.presence_of_element_located((By.NAME, _RECEIPT_FROM_FIELD_NAME))
            )
            receipt_to_field = wait.until(
                EC.presence_of_element_located((By.NAME, _RECEIPT_TO_FIELD_NAME))
            )
            show_records_field = wait.until(
                EC.presence_of_element_located((By.NAME, _SHOW_RECORDS_FIELD_NAME))
            )
        except Exception as e:
            logger.error(f"Timed out waiting for FCC ELS search form fields: {e}")
            return []

        # --- Fill the form ------------------------------------------------
        receipt_from = _receipt_date_from()
        receipt_to = _receipt_date_to()
        logger.info(
            "Filling FCC ELS search: licensee=%r, receipt_from=%s, "
            "receipt_to=%s, show_records=%s",
            config.FCC_ELS_SEARCH_TERM,
            receipt_from,
            receipt_to,
            config.FCC_ELS_RECORD_LIMIT,
        )
        try:
            licensee_field.clear()
        except Exception:
            pass
        licensee_field.send_keys(config.FCC_ELS_SEARCH_TERM)

        try:
            receipt_from_field.clear()
        except Exception:
            pass
        receipt_from_field.send_keys(receipt_from)

        try:
            receipt_to_field.clear()
        except Exception:
            pass
        receipt_to_field.send_keys(receipt_to)

        # show-records is a plain text input pre-filled with a default of "10".
        # Clear the default before typing the configured record limit.
        try:
            show_records_field.clear()
        except Exception:
            pass
        try:
            show_records_field.send_keys(str(config.FCC_ELS_RECORD_LIMIT))
        except Exception as e:
            logger.info(f"Could not set FCC ELS show-records field: {e}")

        # --- Submit the search --------------------------------------------
        try:
            licensee_field.submit()
            logger.info("Submitted FCC ELS search form")
        except Exception as e:
            logger.error(f"Failed to submit FCC ELS search form: {e}")
            return []

        # --- Wait for the results table -----------------------------------
        try:
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, _RESULTS_TABLE_CSS)
                )
            )
        except Exception as e:
            logger.error(f"Timed out waiting for FCC ELS results table: {e}")
            return []

        # --- Parse the results page ---------------------------------------
        rows = parse_fcc_els_results_html(driver.page_source)
        logger.info(f"Parsed {len(rows)} FCC ELS result row(s)")

        # --- Per-row detail retrieval and merge ---------------------------
        for row in rows:
            file_number = row.get("file_number")
            # The parser returns the raw href as scraped, which on this site is
            # a root-relative URL (e.g. "/oetcf/els/reports/STA_Print.cfm?..").
            # Selenium's driver.get() requires an absolute URL, so resolve it
            # against the search page URL (same scheme/host).
            raw_detail_url = row.get("current_detail_url")
            detail_url = urljoin(config.FCC_ELS_SEARCH_URL, raw_detail_url)
            detail: dict | None = None

            for attempt in range(1, _DETAIL_MAX_ATTEMPTS + 1):
                try:
                    driver.set_page_load_timeout(_PAGE_LOAD_TIMEOUT)
                    driver.get(detail_url)
                    detail = parse_fcc_els_detail_html(driver.page_source)
                    break
                except Exception as e:
                    logger.info(
                        "FCC ELS detail attempt %d/%d failed for file_number "
                        "%r: %s",
                        attempt,
                        _DETAIL_MAX_ATTEMPTS,
                        file_number,
                        e,
                    )

            if detail is None:
                # All retries exhausted (or a parse failure). Discard the
                # partial data for this row and continue with the next.
                logger.error(
                    "Discarding FCC ELS application %r: failed to retrieve or "
                    "parse detail page after %d attempts",
                    file_number,
                    _DETAIL_MAX_ATTEMPTS,
                )
                continue

            app = {
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
            results.append(app)

    except Exception as e:
        # Any unexpected search/navigation failure is fail-safe: log and
        # return whatever was accumulated (never raise to the caller).
        logger.error(f"FCC ELS scrape failed: {e}")
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    return results


if __name__ == "__main__":
    apps = fetch_fcc_els_applications()
    logger.info(f"Total FCC ELS applications extracted: {len(apps)}")
