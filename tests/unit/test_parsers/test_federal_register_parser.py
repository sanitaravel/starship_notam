"""Unit tests for the Federal Register search-results parser."""

from __future__ import annotations

import json

from src.parsers.federal_register_parser import (
    parse_federal_register_documents,
)

_PAYLOAD = {
    "count": 3,
    "results": [
        {
            "document_number": "2026-20963",
            "title": "Notice of Intent To Prepare a PEIS ",
            "type": "Notice",
            "abstract": "FAA is announcing its intent to prepare a PEIS.",
            "publication_date": "2026-10-14",
            "html_url": "https://www.federalregister.gov/documents/2026/10/14/2026-20963/x",
            "pdf_url": "https://www.govinfo.gov/content/pkg/FR-2026-10-14/pdf/2026-20963.pdf",
            "comments_close_on": None,
        },
        {"document_number": "", "title": "no number"},
        "junk",
        {
            "document_number": "2026-19897",
            "title": "SLC-37 SEIS",
            "type": "Notice",
            "abstract": None,
            "publication_date": "2026-09-30",
            "html_url": "https://example.test/2026-19897",
            "pdf_url": None,
            "comments_close_on": "2026-10-30",
        },
    ],
}


def test_parses_results_in_server_order_and_drops_rows_without_number():
    records = parse_federal_register_documents(_PAYLOAD)

    assert [r["document_number"] for r in records] == ["2026-20963", "2026-19897"]
    assert records[0] == {
        "document_number": "2026-20963",
        "title": "Notice of Intent To Prepare a PEIS",
        "doc_type": "Notice",
        "abstract": "FAA is announcing its intent to prepare a PEIS.",
        "publication_date": "2026-10-14",
        "comments_close_on": "",
        "html_url": "https://www.federalregister.gov/documents/2026/10/14/2026-20963/x",
        "pdf_url": "https://www.govinfo.gov/content/pkg/FR-2026-10-14/pdf/2026-20963.pdf",
    }
    assert records[1]["abstract"] == ""
    assert records[1]["pdf_url"] == ""
    assert records[1]["comments_close_on"] == "2026-10-30"


def test_accepts_raw_json_text():
    assert parse_federal_register_documents(json.dumps(_PAYLOAD)) == (
        parse_federal_register_documents(_PAYLOAD)
    )


def test_search_without_matches_has_no_results_key():
    assert parse_federal_register_documents({"count": 0, "description": "..."}) == []


def test_junk_input_yields_empty_list():
    assert parse_federal_register_documents("not json") == []
    assert parse_federal_register_documents([1, 2]) == []
    assert parse_federal_register_documents({"results": "nope"}) == []
