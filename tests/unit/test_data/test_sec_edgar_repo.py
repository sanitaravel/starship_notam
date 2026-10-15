"""Unit tests for SEC EDGAR persistence (``data.sec_edgar_repo``)."""

from __future__ import annotations

import pytest

from src.data.sec_edgar_repo import sec_edgar_filings

pytestmark = pytest.mark.usefixtures("initialized_db")


def _filing(accession="0001628280-26-056945", form="8-K", items="2.01,3.02,9.01"):
    return {
        "accession_number": accession,
        "form": form,
        "items": items,
        "filing_date": "2026-08-14",
        "report_date": "2026-08-14",
        "acceptance_datetime": "2026-08-14T12:23:02.000Z",
        "description": form,
        "document_url": f"https://www.sec.gov/Archives/{accession}.htm",
        "index_url": f"https://www.sec.gov/Archives/{accession}-index.htm",
    }


def test_new_filing_needs_post(db_path):
    assert sec_edgar_filings.save(_filing(), db_path) == "inserted"

    rows = sec_edgar_filings.needing_post(db_path)

    assert [r["accession_number"] for r in rows] == ["0001628280-26-056945"]
    assert rows[0]["form"] == "8-K"
    assert rows[0]["items"] == "2.01,3.02,9.01"
    assert rows[0]["acceptance_datetime"] == "2026-08-14T12:23:02.000Z"
    assert rows[0]["index_url"] == "https://www.sec.gov/Archives/0001628280-26-056945-index.htm"


def test_saving_same_filing_twice_is_unchanged(db_path):
    sec_edgar_filings.save(_filing(), db_path)

    assert sec_edgar_filings.save(_filing(), db_path) == "unchanged"
    assert len(sec_edgar_filings.needing_post(db_path)) == 1


def test_posted_filing_is_not_reposted_when_changed(db_path):
    sec_edgar_filings.save(_filing(), db_path)
    sec_edgar_filings.mark_posted("0001628280-26-056945", "42", db_path)

    assert sec_edgar_filings.save(_filing(items="2.01,9.01"), db_path) == "updated"
    assert sec_edgar_filings.needing_post(db_path) == []


def test_needing_post_is_in_insertion_order(db_path):
    for accession in ("a", "b", "c"):
        sec_edgar_filings.save(_filing(accession=accession), db_path)

    rows = sec_edgar_filings.needing_post(db_path)
    assert [r["accession_number"] for r in rows] == ["a", "b", "c"]


def test_record_without_accession_number_is_skipped(db_path):
    assert sec_edgar_filings.save({"form": "8-K"}, db_path) == "skipped"
    assert sec_edgar_filings.needing_post(db_path) == []
