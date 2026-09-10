"""Selenium-based FAA NOTAM search automation.

This module drives the FAA NOTAM Search web application to run a free-text
search for a keyword and extract the resulting NOTAM rows (including each row's
full ICAO message).

The heavy Selenium dependency is imported lazily inside :func:`search_notams`
so that importing this module does not require Selenium to be installed. This
keeps the scraper layer independently importable in test environments.

The scraper performs no persistence: it returns the scraped results to the
caller and raises an exception (or returns an empty list) on failure.
"""

import os
import time

from starship_notam.core.logging import logger

# Whether to run a local Chrome instance (DEBUG_MODE) or connect to a remote
# Selenium grid. Read once at import time to preserve prior behavior.
DEBUG_MODE = os.environ.get("DEBUG_MODE") == "1"


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
    # Lazy imports — selenium is an optional heavy dependency only needed at
    # call time, not at module import time.
    from selenium import webdriver
    from selenium.webdriver import Remote
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    options = webdriver.ChromeOptions()
    # run Chrome in headless mode for automated runs
    options.add_argument("--headless")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--window-position=-2400,-2400")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    # make headless less detectable
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    # set a common user-agent to avoid headless detection
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
    )

    if DEBUG_MODE:
        driver = webdriver.Chrome(options=options)
    else:
        driver = Remote(
            command_executor="http://selenium:4444/wd/hub",
            options=options,
        )

    results = []

    try:
        url = "https://notams.aim.faa.gov/notamSearch/nsapp.html#/"
        logger.info(f"Opening page: {url}")
        driver.get(url)
        wait = WebDriverWait(driver, 20)

        # if a consent/acknowledgement modal appears, click the "I've read and understood" button
        try:
            logger.info("Checking for consent/acknowledgement dialog...")
            # wait for page to be interactive
            try:
                WebDriverWait(driver, 20).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )
            except Exception:
                pass

            # First try a JS-based click to dismiss modal (works in headless)
            try:
                js_try_click = """
                (function(){
                    var texts = ["I've read and understood", "I've read", 'I agree', 'Agree', 'Accept'];
                    for (var t of texts){
                        var xp = "//button[contains(normalize-space(.), '"+t+"')]";
                        try{
                            var res = document.evaluate(xp, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
                            if(res && res.snapshotLength>0){ res.snapshotItem(0).click(); return true; }
                        }catch(e){}
                        // try labels
                        try{
                            var labxp = "//label[contains(normalize-space(.), '"+t+"')]";
                            var r2 = document.evaluate(labxp, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
                            if(r2 && r2.snapshotLength>0){ r2.snapshotItem(0).click(); return true; }
                        }catch(e){}
                    }
                    return false;
                })();
                """
                clicked = driver.execute_script(js_try_click)
                if clicked:
                    logger.info("Dismissed consent dialog via JS click")
                else:
                    # fallback to selenium-based clicks
                    consent_xpaths = [
                        "//button[contains(., \"I've read and understood\")]",
                        "//button[contains(., \"I've read\")]",
                        "//label[contains(., \"I've read\") or contains(., \"read and understood\")]",
                        "//button[contains(., 'I agree') or contains(., 'Agree') or contains(., 'Accept') ]",
                    ]
                    consent_clicked = False
                    for xp in consent_xpaths:
                        try:
                            el = WebDriverWait(driver, 5).until(
                                EC.element_to_be_clickable((By.XPATH, xp))
                            )
                            el.click()
                            consent_clicked = True
                            logger.info(f"Clicked consent element using xpath: {xp}")
                            break
                        except Exception:
                            continue
                    if not consent_clicked:
                        logger.info("No consent dialog found or clickable.")
            except Exception as e:
                logger.info(f"Consent check error: {e}")
        except Exception as e:
            logger.info(f"Consent check error: {e}")

        # open the Location dropdown and select the "Free text" option if present
        try:
            logger.info("Opening Location dropdown and selecting 'Free text' if available...")
            dropdown_btn_xpaths = [
                "//button[contains(@class,'selectpicker') and contains(@title,'Location')]",
                "//button[contains(@class,'dropdown-toggle') and contains(.,'Location')]",
            ]
            dropdown_clicked = False
            for db_xp in dropdown_btn_xpaths:
                try:
                    db = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH, db_xp))
                    )
                    db.click()
                    dropdown_clicked = True
                    logger.info(f"Clicked Location dropdown using xpath: {db_xp}")
                    break
                except Exception:
                    continue

            item_xpaths = [
                "//a[normalize-space()='Free text']",
                "//a[normalize-space()='Free Text']",
                "//li//a[contains(.,'Free text') or contains(.,'Free Text')]",
                "//label[contains(.,'Free text') or contains(.,'Free Text')]",
                "//button[normalize-space()='Free text']",
            ]
            free_selected = False
            for it_xp in item_xpaths:
                try:
                    itm = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH, it_xp))
                    )
                    itm.click()
                    free_selected = True
                    logger.info(f"Selected 'Free text' using xpath: {it_xp}")
                    break
                except Exception:
                    continue
            if not free_selected:
                logger.info("'Free text' option not found in Location dropdown.")
        except Exception as e:
            logger.info(f"Location dropdown error: {e}")

        # Click the "Free Text" tab (optional)
        try:
            logger.info("Clicking 'Free Text' tab (if present)...")
            free_text_tab = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable(
                    (
                        By.XPATH,
                        "//a[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'free text')]",
                    )
                )
            )
            free_text_tab.click()
            logger.info("Clicked 'Free Text' tab")
        except Exception:
            logger.info("No explicit 'Free Text' tab found or clickable.")

        # Type into the free text search box (try multiple selectors)
        search_box = None
        input_xpaths = [
            "//input[contains(@ng-model,'freeFormText') or contains(@ng-model,'freeForm') ]",
            "//input[@placeholder='Enter free text']",
            "//input[contains(@placeholder,'Ex:') or contains(@placeholder,'Enter whole word') ]",
            "//input[@title and contains(@title,'Enter whole word')]",
            "//input[contains(@class,'form-control') and (contains(@placeholder,'Ex:') or contains(@title,'Enter whole word'))]",
        ]
        found_xp = None
        for xp in input_xpaths:
            try:
                search_box = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, xp))
                )
                found_xp = xp
                break
            except Exception:
                continue

        if search_box:
            try:
                search_box.clear()
            except Exception:
                pass
            search_box.send_keys(keyword)
            logger.info(f"Filled free-text input (xpath used: {found_xp}) with '{keyword}'")
        else:
            # fallback: set value via JS on the expected model input
            try:
                driver.execute_script(
                    "var el = document.querySelector('input[ng-model*="
                    + '"freeFormText"'
                    + "]'); if(el){el.value = arguments[0]; el.dispatchEvent(new Event('input'));}",
                    keyword,
                )
                logger.info("Filled free-text input via JS fallback")
            except Exception as e:
                logger.info(f"Could not fill free-text input: {e}")

        # Click Search button (try ng-click and text fallbacks)
        search_clicked = False
        search_xpaths = [
            "//button[contains(@ng-click,'searchNotams') and contains(@class,'btn-primary')]",
            "//button[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'search') and contains(@class,'btn-primary')]",
            "//button[contains(@class,'btn') and contains(.,'Search')]",
        ]
        for xp in search_xpaths:
            try:
                btn = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, xp))
                )
                btn.click()
                search_clicked = True
                logger.info(f"Clicked Search button using xpath: {xp}")
                break
            except Exception:
                continue

        if not search_clicked:
            try:
                # last resort: click first .btn.btn-primary
                btn = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "button.btn.btn-primary"))
                )
                btn.click()
                logger.info("Clicked Search button using CSS fallback .btn.btn-primary")
            except Exception:
                logger.info("Could not click Search button (no clickable selector found)")

        # Wait for results table rows to appear
        try:
            rows = WebDriverWait(driver, 20).until(
                EC.presence_of_all_elements_located(
                    (By.CSS_SELECTOR, "table.table tbody tr.resultRow")
                )
            )
        except Exception:
            rows = driver.find_elements(By.CSS_SELECTOR, "table.table tbody tr.resultRow")

        # Parse each result row into structured fields and extract full NOTAM after clicking
        data = []
        total = len(rows)
        logger.info(f"Found {total} result rows")
        for i in range(total):
            try:
                # re-find the row by index to avoid stale element
                row_xpath = f"(//table[contains(@class,'table')]//tbody//tr[contains(@class,'resultRow')])[{i+1}]"
                tr = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.XPATH, row_xpath))
                )
                # read basic columns before clicking
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
                    f"Processing row {i+1}/{total}: {entry.get('number', '<no-number>')} at {entry.get('location', '')}"
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

                # wait for the NOTAM detail text to appear and ensure it actually updated
                try:
                    # capture previous preview text (if any) so we can detect a change
                    prev_text = ""
                    try:
                        prev_el = driver.find_element(
                            By.XPATH,
                            "//span[contains(@ng-bind-html,'selectedNOTAM.icaoMessage') or contains(@ng-bind-html,'globalScope.selectedNOTAM.traditionalMessage')]",
                        )
                        prev_text = prev_el.text.strip()
                    except Exception:
                        prev_text = ""

                    # wait for the element to be present first
                    WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located(
                            (
                                By.XPATH,
                                "//span[contains(@ng-bind-html,'selectedNOTAM.icaoMessage') or contains(@ng-bind-html,'globalScope.selectedNOTAM.traditionalMessage')]",
                            )
                        )
                    )

                    # then wait (short) until the element's text is non-empty and differs
                    def _non_empty_and_changed(drv):
                        try:
                            el = drv.find_element(
                                By.XPATH,
                                "//span[contains(@ng-bind-html,'selectedNOTAM.icaoMessage') or contains(@ng-bind-html,'globalScope.selectedNOTAM.traditionalMessage')]",
                            )
                            txt = el.text.strip()
                            if not txt:
                                return False
                            if prev_text and txt == prev_text:
                                return False
                            return True
                        except Exception:
                            return False

                    try:
                        WebDriverWait(driver, 5).until(_non_empty_and_changed)
                    except Exception:
                        # best-effort: proceed even if it didn't change in time
                        pass

                    icao_el = driver.find_element(
                        By.XPATH,
                        "//span[contains(@ng-bind-html,'selectedNOTAM.icaoMessage') or contains(@ng-bind-html,'globalScope.selectedNOTAM.traditionalMessage')]",
                    )
                    entry["icao_message"] = icao_el.text.strip()
                    logger.info(f"Extracted ICAO message ({len(entry['icao_message'])} chars)")
                except Exception:
                    # try alternate selector
                    try:
                        icao_el = driver.find_element(
                            By.CSS_SELECTOR,
                            "span[ng-bind-html*='selectedNOTAM.icaoMessage'], span[ng-bind-html*='globalScope.selectedNOTAM.traditionalMessage']",
                        )
                        entry["icao_message"] = icao_el.text.strip()
                        logger.info(
                            f"Extracted ICAO message via CSS ({len(entry['icao_message'])} chars)"
                        )
                    except Exception:
                        entry["icao_message"] = ""
                        logger.info("Could not extract ICAO message for this row")
                        # final fallback: try to read from page JS variables (Angular/globalScope)
                        try:
                            js_script = (
                                "return (window.globalScope && globalScope.selectedNOTAM && globalScope.selectedNOTAM.traditionalMessage) || "
                                "(window.selectedNOTAM && selectedNOTAM.icaoMessage) || (window.selectedNOTAM && selectedNOTAM.traditionalMessage) || ''"
                            )
                            js_val = driver.execute_script(js_script)
                            if js_val:
                                entry["icao_message"] = str(js_val).strip()
                                logger.info(
                                    f"Extracted ICAO message via JS ({len(entry['icao_message'])} chars)"
                                )
                            else:
                                entry["icao_message"] = ""
                                logger.info("Could not extract ICAO message for this row")
                        except Exception:
                            entry["icao_message"] = ""
                            logger.info("Could not extract ICAO message for this row")

                data.append(entry)

                # click Back to Results to return
                try:
                    back_xpaths = [
                        "//button[contains(.,'Back to Results') or contains(.,'Back')]",
                        "//a[contains(.,'Back to Results') or contains(.,'Back')]",
                    ]
                    clicked_back = False
                    for bx in back_xpaths:
                        try:
                            b = WebDriverWait(driver, 5).until(
                                EC.element_to_be_clickable((By.XPATH, bx))
                            )
                            b.click()
                            clicked_back = True
                            break
                        except Exception:
                            continue
                    if not clicked_back:
                        # try closing detail pane via ESC
                        try:
                            from selenium.webdriver.common.keys import Keys

                            driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                        except Exception:
                            pass
                except Exception:
                    pass

                # wait for rows to be present again before next iteration
                WebDriverWait(driver, 20).until(
                    EC.presence_of_all_elements_located(
                        (By.CSS_SELECTOR, "table.table tbody tr.resultRow")
                    )
                )

            except Exception:
                # if anything fails for this row, continue to next
                continue

        results = data

    finally:
        # give a short pause so the browser stays visible briefly
        time.sleep(5)
        driver.quit()

    return results


if __name__ == "__main__":
    notams = search_notams("STARSHIP")
    logger.info(f"Total NOTAMs extracted: {len(notams)}")
