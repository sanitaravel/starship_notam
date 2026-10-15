"""Unit tests for SEC EDGAR submissions parsing (``parsers.sec_edgar_parser``)."""

from __future__ import annotations

import json

from src.parsers.sec_edgar_parser import parse_sec_edgar_filings

# Shaped like data.sec.gov/submissions/CIK0001181412.json (2026-10-15), newest
# first, trimmed to a few columns and rows.
PAYLOAD = {
    "cik": "0001181412",
    "name": "SPACE EXPLORATION TECHNOLOGIES CORP",
    "filings": {
        "recent": {
            "accessionNumber": [
                "0001628280-26-063378",
                "0001628280-26-056945",
                "0001628280-26-052535",
                "9999999995-26-001968",
            ],
            "filingDate": ["2026-09-24", "2026-08-14", "2026-08-04", "2026-06-11"],
            "reportDate": ["2026-04-18", "2026-08-14", "2026-06-30", ""],
            "acceptanceDateTime": [
                "2026-09-24T20:11:01.000Z",
                "2026-08-14T12:23:02.000Z",
                "2026-08-04T20:05:48.000Z",
                "2026-06-12T04:15:20.000Z",
            ],
            "form": ["4", "8-K", "10-Q", "EFFECT"],
            "items": ["", "2.01,3.02,9.01", "", ",,"],
            "primaryDocument": [
                "xslF345X06/wk-form4_1790280657.xml",
                "spcx-20260814.htm",
                "spcx-20260630.htm",
                "xslEFFECTX01/primary_doc.xml",
            ],
            "primaryDocDescription": ["FORM 4", "8-K", "10-Q", ""],
        },
        "files": [],
    },
}


def test_parses_all_filings_newest_first():
    filings = parse_sec_edgar_filings(PAYLOAD)

    assert [f["form"] for f in filings] == ["4", "8-K", "10-Q", "EFFECT"]
    eight_k = filings[1]
    assert eight_k == {
        "accession_number": "0001628280-26-056945",
        "form": "8-K",
        "items": "2.01,3.02,9.01",
        "filing_date": "2026-08-14",
        "report_date": "2026-08-14",
        "acceptance_datetime": "2026-08-14T12:23:02.000Z",
        "description": "8-K",
        "document_url": (
            "https://www.sec.gov/Archives/edgar/data/1181412/"
            "000162828026056945/spcx-20260814.htm"
        ),
        "index_url": (
            "https://www.sec.gov/Archives/edgar/data/1181412/"
            "000162828026056945/0001628280-26-056945-index.htm"
        ),
    }


def test_blank_item_codes_are_dropped():
    assert parse_sec_edgar_filings(PAYLOAD)[3]["items"] == ""


def test_keeps_only_the_given_forms():
    filings = parse_sec_edgar_filings(json.dumps(PAYLOAD), ("8-K", "10-Q"))

    assert [f["accession_number"] for f in filings] == [
        "0001628280-26-056945",
        "0001628280-26-052535",
    ]


def test_short_columns_give_blank_fields():
    payload = {
        "cik": "1181412",
        "filings": {"recent": {"accessionNumber": ["0001-26-1"], "form": ["8-K"]}},
    }

    (filing,) = parse_sec_edgar_filings(payload)

    assert filing["items"] == ""
    assert filing["filing_date"] == ""
    assert filing["document_url"] == ""
    assert filing["index_url"].endswith("/1181412/0001261/0001-26-1-index.htm")


def test_filing_without_accession_number_is_skipped():
    payload = {"cik": "1", "filings": {"recent": {"accessionNumber": [""], "form": ["8-K"]}}}

    assert parse_sec_edgar_filings(payload) == []


def test_junk_input_yields_empty_list():
    assert parse_sec_edgar_filings("not json") == []
    assert parse_sec_edgar_filings([]) == []
    assert parse_sec_edgar_filings({"filings": {}}) == []
    assert parse_sec_edgar_filings({"filings": {"recent": {"form": ["8-K"]}}}) == []
