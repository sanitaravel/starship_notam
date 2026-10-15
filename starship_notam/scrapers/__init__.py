"""Scrapers package: external data fetching via HTTP and Selenium.

Re-exports the public scraper entry points:
    from starship_notam.scrapers import faa_advisory_fetcher, search_notams

The plain-HTTP sources are :class:`~starship_notam.scrapers.http_fetcher.HttpFetcher`
instances (call ``.fetch()``); the Selenium sources are functions.

Heavy dependencies (e.g. ``selenium``) are imported lazily inside the
individual scraper functions so that importing this package does not require
those packages to be installed.
"""

from starship_notam.scrapers.compass_fetcher import compass_files_fetcher
from starship_notam.scrapers.faa_fetcher import faa_advisory_fetcher
from starship_notam.scrapers.faa_license_fetcher import fetch_faa_license
from starship_notam.scrapers.fcc_els_fetcher import fetch_fcc_els_applications
from starship_notam.scrapers.federal_register_fetcher import federal_register_documents_fetcher
from starship_notam.scrapers.notam_scraper import search_notams, search_notams_many
from starship_notam.scrapers.starbase_fetcher import starbase_status_fetcher

__all__ = [
    "search_notams",
    "search_notams_many",
    "faa_advisory_fetcher",
    "fetch_faa_license",
    "starbase_status_fetcher",
    "fetch_fcc_els_applications",
    "compass_files_fetcher",
    "federal_register_documents_fetcher",
]
