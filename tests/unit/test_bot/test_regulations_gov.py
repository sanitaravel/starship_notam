"""Tests for Regulations.gov document formatting, posting and prefill."""

from __future__ import annotations

import pytest

import prefill_regulations_gov
from src.bot.formatting import format_regulations_gov_document
from src.bot.orchestrator import posting, regulations_gov
from src.core import config
from src.data.federal_register_repo import federal_register_documents
from src.data.regulations_gov_repo import regulations_gov_documents
from src.scrapers import regulations_gov_fetcher


def _doc(document_id, posted, title="Notice", **extra):
    return {
        "document_id": document_id,
        "docket_id": document_id.rsplit("-", 1)[0],
        "agency_id": "FAA",
        "document_type": "Notice",
        "subtype": "",
        "title": title,
        "fr_doc_num": "",
        "posted_date": posted,
        "comment_end_date": "",
        **extra,
    }


def test_format_escapes_translates_and_links():
    text = format_regulations_gov_document(
        _doc(
            "FAA-2026-12808-0001",
            "2026-10-14T04:00:00Z",
            title="Starship <Starbase> PEIS",
            subtype="Request for Comments",
            fr_doc_num="2026-20963",
            comment_end_date="2026-12-01T04:59:59Z",
            files=[
                {"title": "", "url": "https://downloads.regulations.gov/a/content.pdf", "format": "pdf"},
                {"title": "FONSI & ROD", "url": "https://downloads.regulations.gov/a/attachment_1.pdf", "format": "pdf"},
            ],
        )
    )

    assert "Regulations.gov: новый документ FAA (Уведомление)" in text
    assert "Starship &lt;Starbase&gt; PEIS" in text
    assert "<b>Вид:</b> Request for Comments" in text
    assert "<b>Докет:</b> FAA-2026-12808" in text
    assert "<b>Опубликован:</b> 14.10.2026" in text
    # 04:59:59Z on 1 December is the last minute of 30 November in Eastern time.
    assert "<b>Комментарии до:</b> 30.11.2026 23:59 ET" in text
    assert '📎 <a href="https://downloads.regulations.gov/a/content.pdf">Документ</a> (PDF)' in text
    assert ">FONSI &amp; ROD</a> (PDF)" in text
    assert 'href="https://www.regulations.gov/document/FAA-2026-12808-0001"' in text
    assert 'href="https://www.regulations.gov/docket/FAA-2026-12808"' in text
    assert 'href="https://www.federalregister.gov/d/2026-20963"' in text
    assert text.endswith("#SpaceUpdates #RegulationsGov #FAA")


def test_format_omits_missing_fields_and_caps_files():
    files = [{"title": f"File {i}", "url": f"https://x/{i}.pdf", "format": "pdf"} for i in range(8)]
    text = format_regulations_gov_document(
        {"document_id": "USCG-2026-1159-0001", "agency_id": "USCG", "document_type": "Odd",
         "title": "T", "files": files}
    )

    assert "(Odd)" in text
    assert "Комментарии до" not in text
    assert "Federal Register" not in text
    assert "File 4" in text and "File 5" not in text
    assert "…и ещё 3 на странице документа" in text
    assert "#USCG" in text


@pytest.fixture
def rg_env(initialized_db, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", initialized_db)
    monkeypatch.setattr(config, "REGULATIONS_GOV_API_KEY", "test-key")
    monkeypatch.setattr(posting, "_SEND_PAUSE_SECONDS", 0)
    sent = []

    async def fake_send(chat_id, text):
        sent.append(text)
        return len(sent)

    monkeypatch.setattr(posting, "send_message", fake_send)

    files_calls = []

    def fake_files_fetch(self):
        files_calls.append(self.document_id)
        return [{"title": "", "url": f"https://x/{self.document_id}.pdf", "format": "pdf"}]

    monkeypatch.setattr(regulations_gov_fetcher.RegulationsGovFiles, "fetch", fake_files_fetch)

    def set_results(by_term):
        """Make each search return ``by_term[term]`` (missing terms: no documents)."""
        monkeypatch.setattr(
            regulations_gov_fetcher.RegulationsGovSearch,
            "fetch",
            lambda self: list(by_term.get(self.term, [])),
        )

    return sent, set_results, files_calls


async def test_documents_from_all_terms_are_merged_and_posted_oldest_first_once(rg_env):
    sent, set_results, files_calls = rg_env
    newer = _doc("FAA-2026-2-0001", "2026-10-14T04:00:00Z", title="Newer")
    older = _doc("USCG-2026-1-0001", "2026-09-15T04:00:00Z", title="Older", agency_id="USCG")
    set_results({"SpaceX": [newer], "Starship": [newer], "Boca Chica": [older]})

    await regulations_gov.process_regulations_gov_documents(["chat"])
    await regulations_gov.process_regulations_gov_documents(["chat"])

    assert len(sent) == 2
    assert "Older" in sent[0] and "#USCG" in sent[0]
    assert "Newer" in sent[1]
    assert 'href="https://x/FAA-2026-2-0001.pdf"' in sent[1]
    assert files_calls == ["USCG-2026-1-0001", "FAA-2026-2-0001"]


async def test_document_already_in_federal_register_is_not_posted(rg_env):
    sent, set_results, _ = rg_env
    federal_register_documents.save({"document_number": "2026-20963", "title": "FR"}, config.DB_PATH)
    set_results(
        {
            "Starship": [
                _doc("FAA-2026-12808-0001", "2026-10-14T04:00:00Z", fr_doc_num="2026-20963"),
                _doc("USCG-2026-1159-0001", "2026-09-15T04:00:00Z", title="Safety zone",
                     fr_doc_num="2026-99999"),
            ]
        }
    )

    await regulations_gov.process_regulations_gov_documents(["chat"])

    assert len(sent) == 1
    assert "Safety zone" in sent[0]
    assert regulations_gov_documents.needing_post() == []


async def test_document_is_deferred_while_its_files_cannot_be_listed(rg_env, monkeypatch):
    sent, set_results, _ = rg_env
    set_results({"SpaceX": [_doc("FAA-2026-1-0001", "2026-10-14T04:00:00Z")]})
    working_fetch = regulations_gov_fetcher.RegulationsGovFiles.fetch
    monkeypatch.setattr(regulations_gov_fetcher.RegulationsGovFiles, "fetch", lambda self: None)

    await regulations_gov.process_regulations_gov_documents(["chat"])
    assert sent == []

    monkeypatch.setattr(regulations_gov_fetcher.RegulationsGovFiles, "fetch", working_fetch)
    await regulations_gov.process_regulations_gov_documents(["chat"])
    assert len(sent) == 1


async def test_source_is_skipped_without_api_key(rg_env, monkeypatch):
    sent, set_results, _ = rg_env
    monkeypatch.setattr(config, "REGULATIONS_GOV_API_KEY", "")

    def must_not_fetch(self):
        raise AssertionError("fetched without a key")

    monkeypatch.setattr(regulations_gov_fetcher.RegulationsGovSearch, "fetch", must_not_fetch)

    await regulations_gov.process_regulations_gov_documents(["chat"])
    assert sent == []
    assert prefill_regulations_gov.main(["--if-empty"]) == 0
    assert regulations_gov_documents.count() == 0


async def test_prefill_suppresses_existing_documents(rg_env):
    sent, set_results, _ = rg_env
    set_results({"SpaceX": [_doc("A-1-0001", "2026-10-14T04:00:00Z")],
                 "Starbase": [_doc("B-1-0001", "2026-09-14T04:00:00Z")]})

    assert regulations_gov.prefill_regulations_gov_documents() == 2
    await regulations_gov.process_regulations_gov_documents(["chat"])
    assert sent == []

    set_results({"SpaceX": [_doc("C-1-0001", "2026-10-20T04:00:00Z", title="Later"),
                            _doc("A-1-0001", "2026-10-14T04:00:00Z")]})
    await regulations_gov.process_regulations_gov_documents(["chat"])
    assert len(sent) == 1
    assert "Later" in sent[0]


def test_prefill_raises_when_any_search_fails(rg_env, monkeypatch):
    _, set_results, _ = rg_env
    monkeypatch.setattr(
        regulations_gov_fetcher.RegulationsGovSearch,
        "fetch",
        lambda self: None if self.term == "Starbase" else [],
    )

    with pytest.raises(RuntimeError):
        regulations_gov.prefill_regulations_gov_documents()


async def test_prefill_script_if_empty_runs_only_on_empty_table(rg_env):
    sent, set_results, _ = rg_env
    set_results({"SpaceX": [_doc("A-1-0001", "2026-10-14T04:00:00Z")]})
    assert prefill_regulations_gov.main(["--if-empty"]) == 0
    assert regulations_gov_documents.needing_post() == []

    # The table now has rows, so a second run must not suppress "B".
    set_results({"SpaceX": [_doc("B-1-0001", "2026-10-20T04:00:00Z", title="Later")]})
    assert prefill_regulations_gov.main(["--if-empty"]) == 0
    await regulations_gov.process_regulations_gov_documents(["chat"])

    assert len(sent) == 1
    assert "Later" in sent[0]


def test_api_key_goes_in_header_not_url(monkeypatch):
    monkeypatch.setattr(config, "REGULATIONS_GOV_API_KEY", "secret")
    search = regulations_gov_fetcher.regulations_gov_searches[0]

    assert search.headers == {"X-Api-Key": "secret"}
    assert "secret" not in search.url
    assert "secret" not in str(search.params())
    assert search.params()["filter[searchTerm]"] == "SpaceX"
    assert search.params()["filter[agencyId]"] == "FAA,USCG"
