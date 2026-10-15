"""Unit tests for Regulations.gov persistence (``data.regulations_gov_repo``)."""

from __future__ import annotations

import pytest

from src.data.regulations_gov_repo import regulations_gov_documents

pytestmark = pytest.mark.usefixtures("initialized_db")


def _doc(document_id="FAA-2026-12808-0001", title="Notice of Intent"):
    return {
        "document_id": document_id,
        "docket_id": "FAA-2026-12808",
        "agency_id": "FAA",
        "document_type": "Notice",
        "subtype": "Request for Comments",
        "title": title,
        "fr_doc_num": "2026-20963",
        "posted_date": "2026-10-14T04:00:00Z",
        "comment_end_date": "2026-12-01T04:59:59Z",
    }


def test_new_document_needs_post(db_path):
    assert regulations_gov_documents.save(_doc(), db_path) == "inserted"

    rows = regulations_gov_documents.needing_post(db_path)

    assert [r["document_id"] for r in rows] == ["FAA-2026-12808-0001"]
    assert rows[0]["fr_doc_num"] == "2026-20963"


def test_changed_document_is_not_reposted(db_path):
    regulations_gov_documents.save(_doc(), db_path)
    regulations_gov_documents.mark_posted("FAA-2026-12808-0001", "42", db_path)

    assert regulations_gov_documents.save(_doc(title="Renamed"), db_path) == "updated"
    assert regulations_gov_documents.needing_post(db_path) == []


def test_document_without_id_is_skipped(db_path):
    assert regulations_gov_documents.save({"title": "x"}, db_path) == "skipped"
    assert regulations_gov_documents.count(db_path) == 0


def test_known_returns_stored_keys_only(db_path):
    regulations_gov_documents.save(_doc("A"), db_path)
    regulations_gov_documents.save(_doc("B"), db_path)
    regulations_gov_documents.mark_posted("B", "1", db_path)

    assert regulations_gov_documents.known(["A", "B", "C"], db_path) == {"A", "B"}
    assert regulations_gov_documents.known([], db_path) == set()
