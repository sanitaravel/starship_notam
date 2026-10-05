"""Selenium-based FAA NOTAM search automation.

This module drives the FAA NOTAM Search web application to run a free-text
search for a keyword and extract the resulting NOTAM rows (including each row's
full ICAO message).

The heavy Selenium dependency is imported lazily inside the search functions
so that importing this module does not require Selenium to be installed. This
keeps the scraper layer independently importable in test environments.

The scraper performs no persistence: it returns the scraped results to the
caller and raises an exception (or returns an empty list) on failure.
"""

from starship_notam.core.logging import logger
from starship_notam.scrapers.driver import create_driver

NOTAM_SEARCH_URL = "https://notams.aim.faa.gov/notamSearch/nsapp.html#/"

# Each step tries several selectors because the FAA page markup has varied.
# They are listed in priority order; one wait checks all of them on every poll,
# so a missing early selector no longer costs a full timeout of its own.
_CONSENT_XPATHS = [
    "//button[contains(., \"I've read and understood\")]",
    "//button[contains(., \"I've read\")]",
    "//label[contains(., \"I've read\") or contains(., \"read and understood\")]",
    "//button[contains(., 'I agree') or contains(., 'Agree') or contains(., 'Accept') ]",
]
_LOCATION_DROPDOWN_XPATHS = [
    "//button[contains(@class,'selectpicker') and contains(@title,'Location')]",
    "//button[contains(@class,'dropdown-toggle') and contains(.,'Location')]",
]
_FREE_TEXT_OPTION_XPATHS = [
    "//a[normalize-space()='Free text']",
    "//a[normalize-space()='Free Text']",
    "//li//a[contains(.,'Free text') or contains(.,'Free Text')]",
    "//label[contains(.,'Free text') or contains(.,'Free Text')]",
    "//button[normalize-space()='Free text']",
]
_FREE_TEXT_TAB_XPATHS = [
    "//a[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'free text')]",
]
_SEARCH_INPUT_XPATHS = [
    "//input[contains(@ng-model,'freeFormText') or contains(@ng-model,'freeForm') ]",
    "//input[@placeholder='Enter free text']",
    "//input[contains(@placeholder,'Ex:') or contains(@placeholder,'Enter whole word') ]",
    "//input[@title and contains(@title,'Enter whole word')]",
    "//input[contains(@class,'form-control') and (contains(@placeholder,'Ex:') or contains(@title,'Enter whole word'))]",
]
_SEARCH_BUTTON_XPATHS = [
    "//button[contains(@ng-click,'searchNotams') and contains(@class,'btn-primary')]",
    "//button[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'search') and contains(@class,'btn-primary')]",
    "//button[contains(@class,'btn') and contains(.,'Search')]",
    # Last resort: the first primary button.
    "//button[contains(concat(' ', normalize-space(@class), ' '), ' btn ') and contains(concat(' ', normalize-space(@class), ' '), ' btn-primary ')]",
]
_BACK_XPATHS = [
    "//button[contains(.,'Back to Results') or contains(.,'Back')]",
    "//a[contains(.,'Back to Results') or contains(.,'Back')]",
]
_ICAO_MESSAGE_XPATH = (
    "//span[contains(@ng-bind-html,'selectedNOTAM.icaoMessage') or "
    "contains(@ng-bind-html,'globalScope.selectedNOTAM.traditionalMessage')]"
)
_RESULT_ROWS_CSS = "table.table tbody tr.resultRow"

# Seconds to wait for each optional page element. The "Free Text" tab has not
# appeared in any logged run, and the consent dialog is only shown once per
# browser session, so those get short waits where possible.
_STEP_TIMEOUT = 5
_OPTIONAL_TAB_TIMEOUT = 1
_REPEAT_CONSENT_TIMEOUT = 1

# Clicks the first consent button/label whose text matches, in page JS. Works
# in headless mode and returns immediately whether or not a dialog exists.
_JS_CLICK_CONSENT = """
(function(){
    var texts = ["I've read and understood", "I've read", 'I agree', 'Agree', 'Accept'];
    for (var t of texts){
        for (var tag of ['button', 'label']){
            var xp = "//" + tag + "[contains(normalize-space(.), '" + t + "')]";
            try{
                var res = document.evaluate(xp, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
                if(res && res.snapshotLength>0){ res.snapshotItem(0).click(); return true; }
            }catch(e){}
        }
    }
    return false;
})();
"""


def _first_clickable(xpaths):
    """Wait condition: the first displayed+enabled element, by xpath priority.

    Returns ``(element, xpath)`` or ``False`` so it can be used with
    ``WebDriverWait.until``.
    """
    from selenium.webdriver.common.by import By

    def condition(driver):
        for xpath in xpaths:
            for element in driver.find_elements(By.XPATH, xpath):
                try:
                    if element.is_displayed() and element.is_enabled():
                        return element, xpath
                except Exception:
                    continue
        return False

    return condition


def _click_first(driver, xpaths, timeout, description):
    """Click the first clickable element among ``xpaths``; return its xpath.

    Returns ``None`` (and logs) when nothing became clickable within
    ``timeout`` seconds, or the click failed.
    """
    from selenium.webdriver.support.ui import WebDriverWait

    try:
        element, xpath = WebDriverWait(driver, timeout).until(_first_clickable(xpaths))
        element.click()
        return xpath
    except Exception:
        logger.info(f"{description}: not found or not clickable")
        return None


def search_notams(keyword: str) -> list[dict]:
    """Search the FAA NOTAM site for ``keyword`` and return structured results.

    Each returned dict contains the keys: ``location``, ``number``, ``class``,
    ``start_date_utc``, ``end_date_utc``, ``condition`` and ``icao_message``
    (a string, which may be empty).

    Selenium is imported lazily so that this module can be imported without the
    ``selenium`` package installed. This function does NOT persist any data.

    Raises:
        ImportError: if Selenium is not installed when this function is called.
        Exception: propagated from the underlying WebDriver on unrecoverable
            navigation/setup errors.
    """
    driver = create_driver()
    try:
        return _search_with_driver(driver, keyword)
    finally:
        driver.quit()


def search_notams_many(keywords) -> dict[str, list[dict]]:
    """Run :func:`search_notams` for several keywords in one browser session.

    Starting Chrome (or a grid session) is the slowest part of a search, so
    the same driver is reused. A failure for one keyword is logged and yields
    an empty list for it; the remaining keywords still run.

    Raises:
        ImportError / Exception: if the browser itself cannot be started.
    """
    driver = create_driver()
    results: dict[str, list[dict]] = {}
    try:
        for index, keyword in enumerate(keywords):
            consent_timeout = _STEP_TIMEOUT if index == 0 else _REPEAT_CONSENT_TIMEOUT
            try:
                results[keyword] = _search_with_driver(driver, keyword, consent_timeout)
            except Exception:
                logger.exception(f"NOTAM search failed for keyword: {keyword}")
                results[keyword] = []
    finally:
        driver.quit()
    return results


def _search_with_driver(driver, keyword: str, consent_timeout: float = _STEP_TIMEOUT) -> list[dict]:
    """Run one free-text search on an existing driver and parse the results."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    # Load from a blank page so a reused session always starts the SPA fresh
    # (navigating to the same hash URL may not reload it).
    driver.get("about:blank")
    logger.info(f"Opening page: {NOTAM_SEARCH_URL}")
    driver.get(NOTAM_SEARCH_URL)

    try:
        WebDriverWait(driver, 20).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
    except Exception:
        pass

    _dismiss_consent(driver, consent_timeout)
    _select_free_text(driver)
    _fill_search_box(driver, keyword)

    xpath = _click_first(driver, _SEARCH_BUTTON_XPATHS, _STEP_TIMEOUT, "Search button")
    if xpath:
        logger.info(f"Clicked Search button using xpath: {xpath}")

    try:
        rows = WebDriverWait(driver, 20).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, _RESULT_ROWS_CSS))
        )
    except Exception:
        rows = driver.find_elements(By.CSS_SELECTOR, _RESULT_ROWS_CSS)

    total = len(rows)
    logger.info(f"Found {total} result rows")
    data = []
    for i in range(total):
        try:
            entry = _read_row(driver, i, total)
        except Exception:
            # if anything fails for this row, continue to next
            continue
        if entry is not None:
            data.append(entry)
    return data


def _dismiss_consent(driver, timeout: float) -> None:
    """Dismiss the consent/acknowledgement dialog if one is shown."""
    logger.info("Checking for consent/acknowledgement dialog...")
    try:
        if driver.execute_script(_JS_CLICK_CONSENT):
            logger.info("Dismissed consent dialog via JS click")
            return
    except Exception as e:
        logger.info(f"Consent JS click error: {e}")
    xpath = _click_first(driver, _CONSENT_XPATHS, timeout, "Consent dialog")
    if xpath:
        logger.info(f"Clicked consent element using xpath: {xpath}")


def _select_free_text(driver) -> None:
    """Switch the Location dropdown (and tab, if any) to free-text search."""
    logger.info("Opening Location dropdown and selecting 'Free text' if available...")
    xpath = _click_first(driver, _LOCATION_DROPDOWN_XPATHS, _STEP_TIMEOUT, "Location dropdown")
    if xpath:
        logger.info(f"Clicked Location dropdown using xpath: {xpath}")
    xpath = _click_first(driver, _FREE_TEXT_OPTION_XPATHS, _STEP_TIMEOUT, "'Free text' option")
    if xpath:
        logger.info(f"Selected 'Free text' using xpath: {xpath}")
    if _click_first(driver, _FREE_TEXT_TAB_XPATHS, _OPTIONAL_TAB_TIMEOUT, "'Free Text' tab"):
        logger.info("Clicked 'Free Text' tab")


def _fill_search_box(driver, keyword: str) -> None:
    """Type ``keyword`` into the free-text input, with a JS fallback."""
    from selenium.webdriver.support.ui import WebDriverWait

    try:
        search_box, xpath = WebDriverWait(driver, _STEP_TIMEOUT).until(
            _first_clickable(_SEARCH_INPUT_XPATHS)
        )
    except Exception:
        search_box = xpath = None

    if search_box is not None:
        try:
            search_box.clear()
        except Exception:
            pass
        search_box.send_keys(keyword)
        logger.info(f"Filled free-text input (xpath used: {xpath}) with '{keyword}'")
        return

    # fallback: set value via JS on the expected model input
    try:
        driver.execute_script(
            "var el = document.querySelector('input[ng-model*=\"freeFormText\"]');"
            " if(el){el.value = arguments[0]; el.dispatchEvent(new Event('input'));}",
            keyword,
        )
        logger.info("Filled free-text input via JS fallback")
    except Exception as e:
        logger.info(f"Could not fill free-text input: {e}")


def _read_row(driver, i: int, total: int) -> dict | None:
    """Open result row ``i``, read its columns and ICAO message, go back."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    # re-find the row by index to avoid stale element
    row_xpath = (
        "(//table[contains(@class,'table')]//tbody//tr[contains(@class,'resultRow')])"
        f"[{i + 1}]"
    )
    tr = WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.XPATH, row_xpath)))
    tds = tr.find_elements(By.TAG_NAME, "td")

    def txt(j):
        try:
            return tds[j].text.strip()
        except Exception:
            return ""

    entry = {
        "location": txt(1),
        "number": txt(2),
        "class": txt(3),
        "start_date_utc": txt(4),
        "end_date_utc": txt(5),
        "condition": txt(6),
        "icao_message": "",
    }
    logger.info(
        f"Processing row {i + 1}/{total}: {entry.get('number', '<no-number>')} "
        f"at {entry.get('location', '')}"
    )

    # click the row to open details
    try:
        tr.click()
    except Exception:
        try:
            driver.execute_script("arguments[0].scrollIntoView(true);", tr)
            tr.click()
        except Exception:
            pass

    entry["icao_message"] = _read_icao_message(driver)

    # click Back to Results to return; fall back to ESC
    if not _click_first(driver, _BACK_XPATHS, _STEP_TIMEOUT, "Back to Results"):
        try:
            driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        except Exception:
            pass

    # wait for rows to be present again before next iteration
    WebDriverWait(driver, 20).until(
        EC.presence_of_all_elements_located((By.CSS_SELECTOR, _RESULT_ROWS_CSS))
    )
    return entry


def _read_icao_message(driver) -> str:
    """Return the selected NOTAM's ICAO text once the detail pane updates."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    try:
        # capture previous preview text (if any) so we can detect a change
        try:
            prev_text = driver.find_element(By.XPATH, _ICAO_MESSAGE_XPATH).text.strip()
        except Exception:
            prev_text = ""

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, _ICAO_MESSAGE_XPATH))
        )

        def non_empty_and_changed(drv):
            try:
                text = drv.find_element(By.XPATH, _ICAO_MESSAGE_XPATH).text.strip()
            except Exception:
                return False
            return bool(text) and not (prev_text and text == prev_text)

        try:
            WebDriverWait(driver, 5).until(non_empty_and_changed)
        except Exception:
            # best-effort: proceed even if it didn't change in time
            pass

        message = driver.find_element(By.XPATH, _ICAO_MESSAGE_XPATH).text.strip()
        logger.info(f"Extracted ICAO message ({len(message)} chars)")
        return message
    except Exception:
        pass

    # final fallback: read from page JS variables (Angular/globalScope)
    try:
        value = driver.execute_script(
            "return (window.globalScope && globalScope.selectedNOTAM && globalScope.selectedNOTAM.traditionalMessage) || "
            "(window.selectedNOTAM && selectedNOTAM.icaoMessage) || (window.selectedNOTAM && selectedNOTAM.traditionalMessage) || ''"
        )
        if value:
            message = str(value).strip()
            logger.info(f"Extracted ICAO message via JS ({len(message)} chars)")
            return message
    except Exception:
        pass
    logger.info("Could not extract ICAO message for this row")
    return ""


if __name__ == "__main__":
    notams = search_notams("STARSHIP")
    logger.info(f"Total NOTAMs extracted: {len(notams)}")
