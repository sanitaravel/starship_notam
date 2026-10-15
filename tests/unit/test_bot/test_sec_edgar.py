"""Tests for SEC EDGAR filing formatting, posting and prefill."""

from __future__ import annotations

import pytest

import prefill_sec_edgar
from src.bot.formatting import format_sec_edgar_filing
from src.bot.orchestrator import posting, sec_edgar
from src.core import config
from src.data.sec_edgar_repo import sec_edgar_filings


def _filing(accession, form="8-K", items="", filed="2026-08-14", **extra):
    return {
        "accession_number": accession,
        "form": form,
        "items": items,
        "filing_date": filed,
        "report_date": "",
        "acceptance_datetime": "",
        "description": form,
        "document_url": f"https://www.sec.gov/Archives/{accession}/doc.htm",
        "index_url": f"https://www.sec.gov/Archives/{accession}-index.htm",
        **extra,
    }


def test_format_8k_names_items_and_links():
    text = format_sec_edgar_filing(
        _filing(
            "0001628280-26-056945",
            items="2.01,3.02,9.99",
            report_date="2026-08-14",
            acceptance_datetime="2026-08-14T12:23:02.000Z",
        )
    )

    assert "SEC EDGAR: новая отчётность SpaceX" in text
    assert "<b>8-K — Существенное событие</b>" in text
    assert "• 2.01 — Завершение приобретения или продажи активов" in text
    assert "• 3.02 — Продажа незарегистрированных акций" in text
    assert "• 9.99" in text
    assert "9.99 —" not in text  # unknown code: number only
    assert "<b>Подана:</b> 14.08.2026 12:23 UTC" in text
    assert "<b>Дата события:</b> 14.08.2026" in text
    assert "Описание" not in text  # the description only repeats the form
    assert 'href="https://www.sec.gov/Archives/0001628280-26-056945/doc.htm"' in text
    assert ">Все файлы</a>" in text
    assert text.endswith("#SpaceUpdates #SEC #SPCX #8K")


def test_format_10q_amendment_shows_period_end():
    text = format_sec_edgar_filing(
        _filing("x", form="10-Q/A", report_date="2026-06-30", description="Amended <Q2>")
    )

    assert "<b>10-Q/A — Квартальный отчёт (поправка)</b>" in text
    assert "<b>Отчётный период до:</b> 30.06.2026" in text
    assert "<b>Описание:</b> Amended &lt;Q2&gt;" in text
    assert "<b>Подана:</b> 14.08.2026" in text  # no acceptance time: filing date
    assert "Пункты 8-K" not in text
    assert text.endswith("#10Q")


@pytest.mark.parametrize(
    "form, heading",
    [
        ("424B4", "<b>424B4 — Проспект выпуска</b>"),
        ("NT 10-K", "<b>NT 10-K — Уведомление о задержке годового отчёта</b>"),
        ("SC TO-T", "<b>SC TO-T</b>"),
    ],
)
def test_format_form_names(form, heading):
    assert heading in format_sec_edgar_filing(_filing("x", form=form))


@pytest.fixture
def edgar_env(initialized_db, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", initialized_db)
    monkeypatch.setattr(config, "SEC_USER_AGENT", "starship_notam test test@example.org")
    monkeypatch.setattr(posting, "_SEND_PAUSE_SECONDS", 0)
    sent = []

    async def fake_send(chat_id, text):
        sent.append(text)
        return len(sent)

    monkeypatch.setattr(posting, "send_message", fake_send)

    def set_filings(filings):
        monkeypatch.setattr(
            sec_edgar.sec_edgar_filings_fetcher, "fetch", lambda: list(filings)
        )

    return sent, set_filings


async def test_new_filings_are_posted_oldest_first_once(edgar_env):
    sent, set_filings = edgar_env
    set_filings(  # newest first, as EDGAR lists them
        [_filing("new", form="10-Q"), _filing("old", form="8-K")]
    )

    await sec_edgar.process_sec_edgar_filings(["chat"])
    await sec_edgar.process_sec_edgar_filings(["chat"])

    assert len(sent) == 2
    assert "8-K" in sent[0]
    assert "10-Q" in sent[1]


async def test_source_is_skipped_without_user_agent(edgar_env, monkeypatch):
    sent, _ = edgar_env
    monkeypatch.setattr(config, "SEC_USER_AGENT", "")

    def must_not_fetch():
        raise AssertionError("fetched without SEC_USER_AGENT")

    monkeypatch.setattr(sec_edgar.sec_edgar_filings_fetcher, "fetch", must_not_fetch)

    await sec_edgar.process_sec_edgar_filings(["chat"])

    assert sent == []
    assert prefill_sec_edgar.main(["--if-empty"]) == 0


async def test_prefill_suppresses_existing_filings(edgar_env):
    sent, set_filings = edgar_env
    set_filings([_filing("b"), _filing("a")])

    assert sec_edgar.prefill_sec_edgar_filings() == 2
    assert sec_edgar_filings.needing_post() == []

    await sec_edgar.process_sec_edgar_filings(["chat"])
    assert sent == []

    set_filings([_filing("c", form="10-K"), _filing("b"), _filing("a")])
    await sec_edgar.process_sec_edgar_filings(["chat"])
    assert len(sent) == 1
    assert "10-K" in sent[0]


def test_prefill_raises_when_fetch_fails(edgar_env, monkeypatch):
    monkeypatch.setattr(sec_edgar.sec_edgar_filings_fetcher, "fetch", lambda: None)

    with pytest.raises(RuntimeError):
        sec_edgar.prefill_sec_edgar_filings()


async def test_prefill_script_if_empty_runs_only_on_empty_table(edgar_env):
    sent, set_filings = edgar_env
    set_filings([_filing("a")])
    assert prefill_sec_edgar.main(["--if-empty"]) == 0
    assert sec_edgar_filings.needing_post() == []

    # The table now has rows, so a second run must not suppress "b".
    set_filings([_filing("b", form="10-Q"), _filing("a")])
    assert prefill_sec_edgar.main(["--if-empty"]) == 0
    await sec_edgar.process_sec_edgar_filings(["chat"])

    assert len(sent) == 1
    assert "10-Q" in sent[0]


async def test_unsent_filing_is_retried_even_when_fetch_fails(edgar_env, monkeypatch):
    sent, set_filings = edgar_env
    working_send = posting.send_message

    async def failing_send(chat_id, text):
        return None

    set_filings([_filing("a")])
    monkeypatch.setattr(posting, "send_message", failing_send)
    await sec_edgar.process_sec_edgar_filings(["chat"])
    assert sent == []

    monkeypatch.setattr(posting, "send_message", working_send)
    monkeypatch.setattr(sec_edgar.sec_edgar_filings_fetcher, "fetch", lambda: None)
    await sec_edgar.process_sec_edgar_filings(["chat"])
    assert len(sent) == 1
