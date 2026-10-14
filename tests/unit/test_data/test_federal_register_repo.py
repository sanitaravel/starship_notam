"""Unit tests for Federal Register persistence (``data.federal_register_repo``)."""

from __future__ import annotations

import pytest

from starship_notam.data.federal_register_repo import (
    get_federal_register_documents_needing_post,
    mark_federal_register_document_posted,
    mark_federal_register_documents_posted,
    save_federal_register_document,
)

pytestmark = pytest.mark.usefixtures("initialized_db")


def _doc(number="2026-20963", title="Notice of Intent", closes=""):
    return {
        "document_number": number,
        "title": title,
        "doc_type": "Notice",
        "abstract": "FAA is announcing...",
        "publication_date": "2026-10-14",
        "comments_close_on": closes,
        "html_url": f"https://www.federalregister.gov/d/{number}",
        "pdf_url": f"https://www.govinfo.gov/{number}.pdf",
    }


def test_new_document_needs_post(db_path):
    assert save_federal_register_document(_doc(), db_path) == "inserted"

    rows = get_federal_register_documents_needing_post(db_path)

    assert [r["document_number"] for r in rows] == ["2026-20963"]
    assert rows[0]["title"] == "Notice of Intent"
    assert rows[0]["doc_type"] == "Notice"
    assert rows[0]["publication_date"] == "2026-10-14"
    assert rows[0]["pdf_url"] == "https://www.govinfo.gov/2026-20963.pdf"


def test_saving_same_document_twice_is_unchanged(db_path):
    save_federal_register_document(_doc(), db_path)

    assert save_federal_register_document(_doc(), db_path) == "unchanged"
    assert len(get_federal_register_documents_needing_post(db_path)) == 1


def test_posted_document_is_not_reposted_when_changed(db_path):
    save_federal_register_document(_doc(), db_path)
    mark_federal_register_document_posted("2026-20963", "42", db_path)

    assert save_federal_register_document(_doc(closes="2026-11-13"), db_path) == "updated"
    assert get_federal_register_documents_needing_post(db_path) == []


def test_needing_post_is_in_insertion_order(db_path):
    for number in ("a", "b", "c"):
        save_federal_register_document(_doc(number=number), db_path)

    rows = get_federal_register_documents_needing_post(db_path)
    assert [r["document_number"] for r in rows] == ["a", "b", "c"]


def test_bulk_mark_skips_already_posted(db_path):
    save_federal_register_document(_doc(number="a"), db_path)
    save_federal_register_document(_doc(number="b"), db_path)
    mark_federal_register_document_posted("a", "42", db_path)

    assert mark_federal_register_documents_posted(["a", "b", "missing"], None, db_path) == 1
    assert get_federal_register_documents_needing_post(db_path) == []


def test_record_without_number_is_skipped(db_path):
    assert save_federal_register_document({"title": "x"}, db_path) == "skipped"
    assert get_federal_register_documents_needing_post(db_path) == []
