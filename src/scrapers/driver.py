"""Shared Selenium WebDriver factory for the Selenium-based scrapers.

Scrapers open a browser with :func:`browser_session`, which always quits it
afterwards. Selenium is imported lazily inside :func:`create_driver` so that
importing this module does not require Selenium to be installed.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from src.core import config
from src.core.logging import logger

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
)


def create_driver():
    """Create a headless, bot-detection-resistant Chrome WebDriver.

    Returns a local ``webdriver.Chrome`` in standalone mode, otherwise (docker
    mode) a ``Remote`` driver connected to the Selenium grid container.

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

    if config.RUN_MODE == "standalone":
        return webdriver.Chrome(options=options)
    return Remote(command_executor=config.SELENIUM_GRID_URL, options=options)


@contextmanager
def browser_session() -> Iterator:
    """Yield a WebDriver from :func:`create_driver` and always quit it afterwards.

    A failure to quit is logged rather than raised, so it cannot replace the
    scrape's own result or error.

    Raises:
        ImportError: if Selenium is not installed.
        Exception: from :func:`create_driver` if the browser cannot be started.
    """
    driver = create_driver()
    try:
        yield driver
    finally:
        try:
            driver.quit()
        except Exception:
            logger.warning("Failed to quit the browser session", exc_info=True)
