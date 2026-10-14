"""Tests for Federal Register document formatting and posting."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from starship_notam.bot import orchestrator
from starship_notam.bot.formatting import format_federal_register_document
from starship_notam.data.federal_register_repo import (
    get_federal_register_documents_needing_post,
)


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
    monkeypatch.setattr(orchestrator.config, "DB_PATH", initialized_db)
    monkeypatch.setattr(orchestrator, "_SEND_PAUSE_SECONDS", 0)
    sent = []

    async def fake_send(chat_id, text):
        sent.append(text)
        return len(sent)

    monkeypatch.setattr(orchestrator, "send_message", fake_send)

    def set_documents(docs):
        monkeypatch.setattr(
            orchestrator, "fetch_federal_register_documents", lambda: list(docs)
        )

    return sent, set_documents


def _days_ago(n):
    return (date.today() - timedelta(days=n)).isoformat()


async def test_new_documents_are_posted_oldest_first_once(fr_env):
    sent, set_documents = fr_env
    set_documents(  # newest first, as the API returns them
        [_doc("new", _days_ago(0), title="Newer"), _doc("old", _days_ago(3), title="Older")]
    )

    await orchestrator._process_federal_register_documents(["chat"])
    await orchestrator._process_federal_register_documents(["chat"])

    assert len(sent) == 2
    assert "Older" in sent[0]
    assert "Newer" in sent[1]


async def test_documents_too_old_when_first_seen_are_not_announced(fr_env):
    sent, set_documents = fr_env
    max_age = orchestrator.config.FEDERAL_REGISTER_MAX_AGE_DAYS
    set_documents(
        [
            _doc("fresh", _days_ago(max_age), title="Fresh"),
            _doc("stale", _days_ago(max_age + 1), title="Stale"),
            _doc("undated", "", title="Undated"),
        ]
    )

    await orchestrator._process_federal_register_documents(["chat"])

    assert len(sent) == 2
    assert not any("Stale" in text for text in sent)
    assert get_federal_register_documents_needing_post() == []


async def test_unsent_document_is_retried_even_when_fetch_fails(fr_env, monkeypatch):
    sent, set_documents = fr_env
    working_send = orchestrator.send_message

    async def failing_send(chat_id, text):
        return None

    set_documents([_doc("a", _days_ago(1))])
    monkeypatch.setattr(orchestrator, "send_message", failing_send)
    await orchestrator._process_federal_register_documents(["chat"])
    assert sent == []

    monkeypatch.setattr(orchestrator, "send_message", working_send)
    monkeypatch.setattr(orchestrator, "fetch_federal_register_documents", lambda: None)
    await orchestrator._process_federal_register_documents(["chat"])
    assert len(sent) == 1
