"""Scrapers package: external data fetching over HTTP.

Re-exports the public scraper entry points:
    from src.scrapers import faa_advisory_fetcher, search_notams

The plain-HTTP sources are :class:`~src.scrapers.http_fetcher.HttpFetcher`
instances (call ``.fetch()``); the sources that need a session (a login
cookie, a form round-trip or paging) are functions.
"""

from src.scrapers.compass_fetcher import compass_files_fetcher
from src.scrapers.faa_fetcher import faa_advisory_fetcher
from src.scrapers.faa_license_fetcher import fetch_faa_license
from src.scrapers.fcc_els_fetcher import fetch_fcc_els_applications
from src.scrapers.federal_register_fetcher import federal_register_documents_fetcher
from src.scrapers.notam_scraper import search_notams, search_notams_many
from src.scrapers.regulations_gov_fetcher import (
    RegulationsGovFiles,
    fetch_regulations_gov_documents,
)
from src.scrapers.sec_edgar_fetcher import sec_edgar_filings_fetcher
from src.scrapers.starbase_fetcher import starbase_status_fetcher

__all__ = [
    "search_notams",
    "search_notams_many",
    "faa_advisory_fetcher",
    "fetch_faa_license",
    "starbase_status_fetcher",
    "fetch_fcc_els_applications",
    "compass_files_fetcher",
    "federal_register_documents_fetcher",
    "fetch_regulations_gov_documents",
    "RegulationsGovFiles",
    "sec_edgar_filings_fetcher",
]
