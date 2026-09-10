"""Scrapers package: external data fetching via HTTP and Selenium.

Re-exports the public scraper entry points:
    from starship_notam.scrapers import search_notams, fetch_faa_advisory, fetch_starbase_status

Heavy dependencies (e.g. ``selenium``) are imported lazily inside the
individual scraper functions so that importing this package does not require
those packages to be installed.
"""

from starship_notam.scrapers.faa_fetcher import fetch_faa_advisory
from starship_notam.scrapers.notam_scraper import search_notams
from starship_notam.scrapers.starbase_fetcher import fetch_starbase_status

__all__ = [
    "search_notams",
    "fetch_faa_advisory",
    "fetch_starbase_status",
]
