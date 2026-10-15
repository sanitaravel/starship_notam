"""Tests for Federal Register document formatting, posting and prefill."""

from __future__ import annotations

import pytest

import prefill_federal_register
from starship_notam.bot.formatting import format_federal_register_document
from starship_notam.bot.orchestrator import federal_register, posting
from starship_notam.core import config
from starship_notam.data.federal_register_repo import federal_register_documents


def _doc(number, published, title="Notice", **extra):
    return {
        "document_number": number,
        "title": title,
        "doc_type": "Notice",
        "abstract": "",
        "publication_date": published,
        "comments_close_on": "",
        "html_url": f"https://www.federalregister.gov/d/{number}",
        "pdf_url": f"https://www.govinfo.gov/{number}.pdf",
        **extra,
    }


def test_format_escapes_translates_and_links():
    text = format_federal_register_document(
        _doc(
            "2026-20963",
            "2026-10-14",
            title="Starship <Starbase> PEIS",
            comments_close_on="2026-11-13",
            abstract="FAA is announcing & requesting comments.",
        )
    )

    assert "Federal Register: новый документ FAA (Уведомление)" in text
    assert "Starship &lt;Starbase&gt; PEIS" in text
    assert "<b>Опубликован:</b> 14.10.2026" in text
    assert "<b>Комментарии до:</b> 13.11.2026" in text
    assert "FAA is announcing &amp; requesting comments." in text
    assert 'href="https://www.federalregister.gov/d/2026-20963"' in text
    assert 'href="https://www.govinfo.gov/2026-20963.pdf">PDF</a>' in text
    assert "#FederalRegister" in text


def test_format_omits_missing_fields_and_keeps_unknown_type():
    text = format_federal_register_document(
        {"document_number": "x", "doc_type": "Correction", "title": "T"}
    )

    assert "(Correction)" in text
    assert "Комментарии до" not in text
    assert "PDF" not in text


def test_format_trims_long_abstract_at_word_boundary():
    text = format_federal_register_document(
        _doc("x", "2026-10-14", abstract="word " * 500)
    )

    abstract = text.split("\n\n")[3]
    assert abstract.endswith("word…")
    assert len(abstract) <= 600


@pytest.fixture
def fr_env(initialized_db, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", initialized_db)
    monkeypatch.setattr(posting, "_SEND_PAUSE_SECONDS", 0)
    sent = []

    async def fake_send(chat_id, text):
        sent.append(text)
        return len(sent)

    monkeypatch.setattr(posting, "send_message", fake_send)

    def set_documents(docs):
        monkeypatch.setattr(federal_register.federal_register_documents_fetcher, "fetch", lambda: list(docs)
        )

    return sent, set_documents


async def test_new_documents_are_posted_oldest_first_once(fr_env):
    sent, set_documents = fr_env
    set_documents(  # newest first, as the API returns them
        [_doc("new", "2026-10-14", title="Newer"), _doc("old", "2026-10-11", title="Older")]
    )

    await federal_register.process_federal_register_documents(["chat"])
    await federal_register.process_federal_register_documents(["chat"])

    assert len(sent) == 2
    assert "Older" in sent[0]
    assert "Newer" in sent[1]


async def test_prefill_suppresses_existing_documents(fr_env):
    sent, set_documents = fr_env
    set_documents([_doc("new", "2026-10-14"), _doc("old", "2026-09-29")])

    assert federal_register.prefill_federal_register_documents() == 2
    assert federal_register_documents.needing_post() == []

    await federal_register.process_federal_register_documents(["chat"])
    assert sent == []

    set_documents([_doc("newer", "2026-10-20", title="Newer"), _doc("new", "2026-10-14")])
    await federal_register.process_federal_register_documents(["chat"])
    assert len(sent) == 1
    assert "Newer" in sent[0]


def test_prefill_raises_when_fetch_fails(initialized_db, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", initialized_db)
    monkeypatch.setattr(federal_register.federal_register_documents_fetcher, "fetch", lambda: None)

    with pytest.raises(RuntimeError):
        federal_register.prefill_federal_register_documents()


async def test_prefill_script_if_empty_runs_only_on_empty_table(fr_env):
    sent, set_documents = fr_env
    set_documents([_doc("a", "2026-10-14")])
    assert prefill_federal_register.main(["--if-empty"]) == 0
    assert federal_register_documents.needing_post() == []

    # The table now has rows, so a second run must not suppress "b".
    set_documents([_doc("b", "2026-10-20", title="Later"), _doc("a", "2026-10-14")])
    assert prefill_federal_register.main(["--if-empty"]) == 0
    await federal_register.process_federal_register_documents(["chat"])

    assert len(sent) == 1
    assert "Later" in sent[0]


async def test_unsent_document_is_retried_even_when_fetch_fails(fr_env, monkeypatch):
    sent, set_documents = fr_env
    working_send = posting.send_message

    async def failing_send(chat_id, text):
        return None

    set_documents([_doc("a", "2026-10-14")])
    monkeypatch.setattr(posting, "send_message", failing_send)
    await federal_register.process_federal_register_documents(["chat"])
    assert sent == []

    monkeypatch.setattr(posting, "send_message", working_send)
    monkeypatch.setattr(federal_register.federal_register_documents_fetcher, "fetch", lambda: None)
    await federal_register.process_federal_register_documents(["chat"])
    assert len(sent) == 1
