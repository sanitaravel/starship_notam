"""Selenium-based FAA DRS launch-license summary fetcher.

This module tracks a single FAA Dynamic Regulatory System (DRS) document -- the
Starship / Super Heavy Vehicle Operator License -- by reading its "Document
Details" metadata from the DRS JSON summary API
(``/api/browse/documents/summaryguiddocview/<DRSDOCID>``).

Why Selenium and not plain ``requests``: the DRS host sits behind an Akamai/AWS
edge that rejects unadorned HTTP clients with ``403``. A real browser first
loads the document viewer page (which sets the ``ak_bmsc`` / ``AWSALB`` session
cookies), after which the same-origin summary endpoint returns ``200``. We
therefore drive a headless browser to the viewer URL and then issue the summary
request *from within the page context* (via ``fetch``), so the established
cookies are attached automatically.

The heavy Selenium dependency is imported lazily inside
:func:`fetch_faa_license` so importing this module (and the ``scrapers``
package) does not require Selenium to be installed.

The scraper performs no persistence: it returns a single normalized record dict
(or ``None``) to the caller and is fail-safe -- it returns ``None`` and never
raises on any navigation/fetch failure. Parsing/normalization is delegated to
the pure function in :mod:`starship_notam.parsers.faa_license_parser`.
"""

import json
import os

from starship_notam.core import config
from starship_notam.core.logging import logger
from starship_notam.parsers.faa_license_parser import parse_faa_license_summary

# Whether to run a local Chrome instance (DEBUG_MODE) or connect to a remote
# Selenium grid. Read once at import time to match the other scrapers.
DEBUG_MODE = os.environ.get("DEBUG_MODE") == "1"

# Seconds to wait for the viewer page (and its Angular app) to load and set the
# edge/session cookies before we call the summary API.
_PAGE_LOAD_TIMEOUT = 45

# Total seconds allowed for the in-page ``fetch`` of the summary JSON.
_SUMMARY_FETCH_TIMEOUT_MS = 30000

# JavaScript executed inside the loaded DRS page. It fetches the summary JSON
# using the page's own (cookie-bearing) session and returns the parsed object,
# or an ``{"__error__": ...}`` marker on failure. Uses an AbortController so a
# hung request cannot block Selenium indefinitely.
_FETCH_SUMMARY_JS = """
const url = arguments[0];
const timeoutMs = arguments[1];
const done = arguments[arguments.length - 1];
const controller = new AbortController();
const timer = setTimeout(() => controller.abort(), timeoutMs);
fetch(url, {
    headers: { "Accept": "application/json" },
    signal: controller.signal,
})
    .then((r) => r.text().then((text) => ({ status: r.status, text })))
    .then((res) => {
        clearTimeout(timer);
        if (res.status !== 200) {
            done({ __error__: "http_status", status: res.status });
            return;
        }
        try {
            done(JSON.parse(res.text));
        } catch (e) {
            done({ __error__: "json_parse", message: String(e) });
        }
    })
    .catch((e) => {
        clearTimeout(timer);
        done({ __error__: "fetch_failed", message: String(e) });
    });
"""


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
    # Lazy imports -- selenium is an optional heavy dependency only needed at
    # call time (keeps the scrapers package importable without selenium).
    try:
        from selenium import webdriver
        from selenium.webdriver import Remote
    except Exception as e:  # pragma: no cover - environment-dependent
        logger.error(f"Selenium is not available for FAA DRS license scrape: {e}")
        return None

    options = webdriver.ChromeOptions()
    # run Chrome in headless mode for automated runs
    options.add_argument("--headless")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--window-position=-2400,-2400")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    # make headless less detectable (the DRS edge blocks obvious bots)
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
    )

    if DEBUG_MODE:
        driver = webdriver.Chrome(options=options)
    else:
        driver = Remote(
            command_executor="http://selenium:4444/wd/hub",
            options=options,
        )

    try:
        viewer_url = config.FAA_LICENSE_VIEWER_URL
        summary_url = config.FAA_LICENSE_SUMMARY_URL

        # 1) Load the viewer page so the edge/session cookies are established.
        logger.info("Opening FAA DRS license viewer page: %s", viewer_url)
        try:
            driver.set_page_load_timeout(_PAGE_LOAD_TIMEOUT)
            driver.get(viewer_url)
        except Exception as e:
            # A page-load timeout is not fatal on its own: the cookies are
            # typically set well before the heavy PDF viewer finishes. Proceed
            # to the summary fetch and let it decide.
            logger.info(
                "FAA DRS viewer page load did not fully complete (continuing "
                "to summary fetch): %s",
                e,
            )

        # 2) Fetch the summary JSON from within the page context (cookies are
        #    attached automatically by the browser).
        logger.info("Fetching FAA DRS license summary JSON: %s", summary_url)
        try:
            driver.set_script_timeout(_SUMMARY_FETCH_TIMEOUT_MS / 1000 + 10)
            payload = driver.execute_async_script(
                _FETCH_SUMMARY_JS, summary_url, _SUMMARY_FETCH_TIMEOUT_MS
            )
        except Exception as e:
            logger.error(f"FAA DRS license summary fetch failed: {e}")
            return None

        if isinstance(payload, dict) and payload.get("__error__"):
            logger.error(
                "FAA DRS license summary request unsuccessful: %s",
                json.dumps(payload, ensure_ascii=False),
            )
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

    except Exception as e:
        # Any unexpected navigation/fetch failure is fail-safe.
        logger.error(f"FAA DRS license scrape failed: {e}")
        return None
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    result = fetch_faa_license()
    logger.info(f"FAA DRS license record: {result}")
