"""SEC EDGAR submissions parsing.

Pure-function parser for the JSON returned by the EDGAR submissions API
(``https://data.sec.gov/submissions/CIK##########.json``). The payload holds
the company's recent filings as parallel arrays, newest first::

    {"cik": "0001181412", "name": "SPACE EXPLORATION TECHNOLOGIES CORP",
     "filings": {"recent": {"accessionNumber": ["0001628280-26-056945", ...],
                            "form": ["8-K", ...],
                            "items": ["2.01,3.02,9.01", ...],
                            "filingDate": ["2026-08-14", ...],
                            "acceptanceDateTime": ["2026-08-14T12:23:02.000Z", ...],
                            "reportDate": ["2026-08-14", ...],
                            "primaryDocument": ["spcx-20260814.htm", ...],
                            "primaryDocDescription": ["8-K", ...], ...},
                 "files": []}}

It performs no network, database, or filesystem operations.

Public API:
    parse_sec_edgar_filings(payload: dict | str, forms=None) -> list[dict]
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Optional

from src.core.logging import logger

_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data"


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _items(value: Any) -> str:
    """``"2.01,3.02,9.01"`` -> the same, without blanks (EFFECT forms have ``",,"``)."""
    return ",".join(code for code in (c.strip() for c in _text(value).split(",")) if code)


def parse_sec_edgar_filings(
    payload: Any, forms: Optional[Iterable[str]] = None
) -> list[dict]:
    """Normalize the submissions payload into a list of filing records.

    Parameters
    ----------
    payload : dict or str
        The parsed JSON, or the raw JSON text.
    forms : iterable of str, optional
        Keep only filings of these form types (e.g. ``"8-K"``, ``"10-Q/A"``);
        all filings are kept when omitted.

    Returns
    -------
    list[dict]
        One record per filing, in the order the server returned them (newest
        first), each with the keys ``accession_number``, ``form``, ``items``
        (8-K item codes joined by commas, or ``""``), ``filing_date``,
        ``report_date`` (ISO dates, or ``""``), ``acceptance_datetime``,
        ``description`` (the primary document's description), ``document_url``
        and ``index_url``. Filings without an accession number are dropped;
        junk input yields ``[]``.
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            logger.error("SEC EDGAR response is not valid JSON")
            return []
    if not isinstance(payload, dict):
        logger.error("SEC EDGAR response is not a JSON object")
        return []

    recent = (payload.get("filings") or {}).get("recent")
    if not isinstance(recent, dict):
        logger.error("SEC EDGAR response has no 'filings.recent' object")
        return []
    accessions = recent.get("accessionNumber")
    if not isinstance(accessions, list):
        logger.error("SEC EDGAR response has no 'accessionNumber' list")
        return []

    # The archive path uses the CIK without leading zeros.
    cik = _text(payload.get("cik")).lstrip("0")
    wanted = set(forms) if forms is not None else None

    def column(name: str, index: int) -> str:
        values = recent.get(name)
        if isinstance(values, list) and index < len(values):
            return _text(values[index])
        return ""

    records = []
    for i, accession in enumerate(accessions):
        accession = _text(accession)
        form = column("form", i)
        if wanted is not None and form not in wanted:
            continue
        if not accession:
            logger.info("Skipping SEC EDGAR %s filing without accession number", form)
            continue

        folder = f"{_ARCHIVES_URL}/{cik}/{accession.replace('-', '')}" if cik else ""
        primary = column("primaryDocument", i)
        records.append(
            {
                "accession_number": accession,
                "form": form,
                "items": _items(column("items", i)),
                "filing_date": column("filingDate", i),
                "report_date": column("reportDate", i),
                "acceptance_datetime": column("acceptanceDateTime", i),
                "description": column("primaryDocDescription", i),
                "document_url": f"{folder}/{primary}" if folder and primary else "",
                "index_url": f"{folder}/{accession}-index.htm" if folder else "",
            }
        )
    return records
