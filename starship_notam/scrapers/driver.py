"""Shared Selenium WebDriver factory for the Selenium-based scrapers.

Selenium is imported lazily inside :func:`create_driver` so that importing
this module does not require Selenium to be installed.
"""

import os

# Whether to run a local Chrome instance (DEBUG_MODE) or connect to a remote
# Selenium grid. Read once at import time to preserve prior behavior.
DEBUG_MODE = os.environ.get("DEBUG_MODE") == "1"

SELENIUM_GRID_URL = "http://selenium:4444/wd/hub"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
)


def create_driver():
    """Create a headless, bot-detection-resistant Chrome WebDriver.

    Returns a local ``webdriver.Chrome`` when ``DEBUG_MODE`` is set, otherwise a
    ``Remote`` driver connected to the Selenium grid.

    Raises:
        ImportError: if Selenium is not installed.
    """
    from selenium import webdriver
    from selenium.webdriver import Remote

    options = webdriver.ChromeOptions()
    # run Chrome in headless mode for automated runs
    options.add_argument("--headless")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--window-position=-2400,-2400")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    # make headless less detectable (some edges block obvious bots)
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument(f"user-agent={USER_AGENT}")

    if DEBUG_MODE:
        return webdriver.Chrome(options=options)
    return Remote(command_executor=SELENIUM_GRID_URL, options=options)
