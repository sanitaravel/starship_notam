"""Unit tests for ``parsers.regulations_gov_parser`` (trimmed live responses, 2026-10-15)."""

from __future__ import annotations

import json

from src.parsers.regulations_gov_parser import (
    parse_regulations_gov_documents,
    parse_regulations_gov_files,
)

SEARCH = {
    "data": [
        {
            "type": "documents",
            "id": "FAA-2026-12808-0001",
            "attributes": {
                "agencyId": "FAA",
                "frDocNum": "2026-20963",
                "documentType": "Notice",
                "withdrawn": False,
                "commentEndDate": "2026-12-01T04:59:59Z",
                "lastModifiedDate": "2026-10-15T09:00:41Z",
                "postedDate": "2026-10-14T04:00:00Z",
                "title": "Notice of Intent To Prepare a Programmatic EIS ... Starbase, Texas",
                "docketId": "FAA-2026-12808",
                "subtype": "Request for Comments",
            },
        },
        {
            "type": "documents",
            "id": "FAA-2025-3124-0030",
            "attributes": {
                "agencyId": "FAA",
                "frDocNum": None,
                "documentType": "Other",
                "withdrawn": False,
                "commentEndDate": None,
                "postedDate": "2026-02-13T05:00:00Z",
                "title": "Final Tiered Environmental Assessment ... Boca Chica",
                "docketId": "FAA-2025-3124",
                "subtype": "Environmental Impact Statement",
            },
        },
        {"type": "documents", "id": "WITHDRAWN-1", "attributes": {"withdrawn": True}},
        {"type": "documents", "attributes": {"title": "no id"}},
        "junk",
    ],
    "meta": {"totalElements": 5},
}


def test_documents_are_normalized_and_bad_rows_dropped():
    records = parse_regulations_gov_documents(SEARCH)

    assert [r["document_id"] for r in records] == ["FAA-2026-12808-0001", "FAA-2025-3124-0030"]
    assert records[0] == {
        "document_id": "FAA-2026-12808-0001",
        "docket_id": "FAA-2026-12808",
        "agency_id": "FAA",
        "document_type": "Notice",
        "subtype": "Request for Comments",
        "title": "Notice of Intent To Prepare a Programmatic EIS ... Starbase, Texas",
        "fr_doc_num": "2026-20963",
        "posted_date": "2026-10-14T04:00:00Z",
        "comment_end_date": "2026-12-01T04:59:59Z",
    }
    assert records[1]["fr_doc_num"] == ""
    assert records[1]["comment_end_date"] == ""


def test_documents_accept_raw_json_text():
    assert len(parse_regulations_gov_documents(json.dumps(SEARCH))) == 2


def test_documents_junk_input_yields_empty_list():
    assert parse_regulations_gov_documents("not json") == []
    assert parse_regulations_gov_documents([1, 2]) == []
    assert parse_regulations_gov_documents({"data": "nope"}) == []
    assert parse_regulations_gov_documents({"data": []}) == []


def _attachment(order, title, n):
    return {
        "type": "attachments",
        "id": f"att{n}",
        "attributes": {
            "title": title,
            "docOrder": order,
            "fileFormats": [
                {
                    "fileUrl": f"https://downloads.regulations.gov/FAA-2025-3124-0030/attachment_{n}.pdf",
                    "format": "pdf",
                    "size": 1000,
                }
            ],
        },
    }


def test_files_list_content_then_attachments_in_doc_order():
    payload = {
        "data": {
            "id": "FAA-2026-12808-0001",
            "attributes": {
                "fileFormats": [
                    {"fileUrl": "https://downloads.regulations.gov/x/content.html", "format": "html"},
                    {"fileUrl": "https://downloads.regulations.gov/x/content.pdf", "format": "pdf"},
                ]
            },
        },
        "included": [
            _attachment(2, "FONSI ROD", 2),
            _attachment(1, "Final Tiered EA", 1),
            {"type": "attachments", "attributes": {"title": "no file", "fileFormats": None}},
            {"type": "other", "attributes": {}},
        ],
    }

    files = parse_regulations_gov_files(payload)

    assert files == [
        {"title": "", "url": "https://downloads.regulations.gov/x/content.pdf", "format": "pdf"},
        {
            "title": "Final Tiered EA",
            "url": "https://downloads.regulations.gov/FAA-2025-3124-0030/attachment_1.pdf",
            "format": "pdf",
        },
        {
            "title": "FONSI ROD",
            "url": "https://downloads.regulations.gov/FAA-2025-3124-0030/attachment_2.pdf",
            "format": "pdf",
        },
    ]


def test_files_without_any_file_is_empty_list():
    assert parse_regulations_gov_files({"data": {"attributes": {"fileFormats": None}}}) == []
    assert parse_regulations_gov_files("junk") == []
