"""Tests for Starship documentary formatting, posting and prefill."""

from __future__ import annotations

import pytest

import prefill_starship_doc
from src.bot.formatting import format_starship_documentary
from src.bot.orchestrator import posting, starship_doc
from src.core import config
from src.data.starship_doc_repo import starship_documentaries


def _episode(number=4, **extra):
    return {
        "episode_id": f"StarshipDoc_Ep{number:03d}",
        "episode": number,
        "duration_seconds": 1270,
        "published_at": "2026-11-06T13:44:03Z",
        "master_url": f"https://example.org/Ep{number:03d}.m3u8",
        "playlist_url": f"https://example.org/Ep{number:03d}-4k.m3u8",
        **extra,
    }


def test_format_episode():
    text = format_starship_documentary(_episode())

    assert text.splitlines()[0] == (
        "<b>🎬 SpaceX: новый эпизод документального сериала о Starship</b>"
    )
    assert "<b>Эпизод 4</b>" in text
    assert "<b>Длительность:</b> 21 мин 10 с" in text
    assert "<b>Опубликован:</b> 06.11.2026 13:44 UTC" in text
    assert '<a href="https://example.org/Ep004.m3u8">Смотреть (HLS)</a>' in text
    assert '<a href="https://example.org/Ep004-4k.m3u8">4K</a>' in text
    assert "Safari" in text
    assert text.endswith("#SpaceUpdates #Starship #Документалка")


def test_format_long_duration_uses_hours():
    assert "<b>Длительность:</b> 1 ч 02 мин" in format_starship_documentary(
        _episode(duration_seconds=3725)
    )


def test_format_omits_missing_lines():
    text = format_starship_documentary(_episode(duration_seconds=0, published_at=""))

    assert "Длительность" not in text
    assert "Опубликован" not in text


def test_format_escapes_source_strings():
    text = format_starship_documentary(_episode(master_url='https://x/?a=1&b="2"'))

    assert 'href="https://x/?a=1&amp;b=&quot;2&quot;"' in text


@pytest.fixture
def doc_env(initialized_db, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", initialized_db)
    monkeypatch.setattr(posting, "_SEND_PAUSE_SECONDS", 0)
    sent = []

    async def fake_send(chat_id, text):
        sent.append(text)
        return len(sent)

    monkeypatch.setattr(posting, "send_message", fake_send)
    asked = []

    def set_online(*numbers):
        def fake_fetch_after(latest):
            asked.append(latest)
            return [_episode(n) for n in numbers if n > latest]

        monkeypatch.setattr(
            starship_doc.starship_documentary_fetcher, "fetch_after", fake_fetch_after
        )

    return sent, asked, set_online


async def test_new_episodes_are_posted_in_order_once(doc_env):
    sent, asked, set_online = doc_env
    set_online(2, 1)

    await starship_doc.process_starship_documentaries(["chat"])
    await starship_doc.process_starship_documentaries(["chat"])

    assert len(sent) == 2
    assert "Эпизод 1" in sent[0]
    assert "Эпизод 2" in sent[1]
    assert asked == [0, 2]  # the second cycle resumes after the stored Ep002


async def test_prefill_suppresses_existing_episodes(doc_env):
    sent, _, set_online = doc_env
    set_online(1, 2)

    assert starship_doc.prefill_starship_documentaries() == 2
    assert starship_documentaries.needing_post() == []

    await starship_doc.process_starship_documentaries(["chat"])
    assert sent == []

    set_online(1, 2, 3)
    await starship_doc.process_starship_documentaries(["chat"])
    assert len(sent) == 1
    assert "Эпизод 3" in sent[0]


def test_prefill_raises_when_fetch_fails(doc_env, monkeypatch):
    monkeypatch.setattr(
        starship_doc.starship_documentary_fetcher, "fetch_after", lambda latest: None
    )

    with pytest.raises(RuntimeError):
        starship_doc.prefill_starship_documentaries()


async def test_prefill_script_if_empty_runs_only_on_empty_table(doc_env):
    sent, _, set_online = doc_env
    set_online(1)
    assert prefill_starship_doc.main(["--if-empty"]) == 0
    assert starship_documentaries.needing_post() == []

    # The table now has rows, so a second run must not suppress Ep002.
    set_online(1, 2)
    assert prefill_starship_doc.main(["--if-empty"]) == 0
    await starship_doc.process_starship_documentaries(["chat"])

    assert len(sent) == 1
    assert "Эпизод 2" in sent[0]


def test_prefill_script_fails_when_fetch_fails(doc_env, monkeypatch):
    monkeypatch.setattr(
        starship_doc.starship_documentary_fetcher, "fetch_after", lambda latest: None
    )

    assert prefill_starship_doc.main([]) == 1


async def test_unsent_episode_is_retried_even_when_fetch_fails(doc_env, monkeypatch):
    sent, _, set_online = doc_env
    working_send = posting.send_message

    async def failing_send(chat_id, text):
        return None

    set_online(1)
    monkeypatch.setattr(posting, "send_message", failing_send)
    await starship_doc.process_starship_documentaries(["chat"])
    assert sent == []

    monkeypatch.setattr(posting, "send_message", working_send)
    monkeypatch.setattr(
        starship_doc.starship_documentary_fetcher, "fetch_after", lambda latest: None
    )
    await starship_doc.process_starship_documentaries(["chat"])
    assert len(sent) == 1
