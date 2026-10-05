"""Tests for COMPASS file formatting, posting and prefill."""

from __future__ import annotations

import pytest

from starship_notam.bot import orchestrator
from starship_notam.bot.formatting import format_compass_file
from starship_notam.data.compass_repo import get_compass_files_needing_post

_FILES = [  # newest first, as the site returns them
    {"file_uuid": "new", "filename": "deck <10 05>.pptx", "uploaded_at": "05/Oct/2026 14:26"},
    {"file_uuid": "old", "filename": "deck 10 01.pptx", "uploaded_at": "01/Oct/2026 14:31"},
]


def test_format_compass_file_escapes_and_links():
    text = format_compass_file(_FILES[0])

    assert "Новый файл в COMPASS" in text
    assert "deck &lt;10 05&gt;.pptx" in text
    assert "05/Oct/2026 14:26" in text
    assert "getfile?download=false&amp;fileuuid=new" in text
    assert "vpublic_anspdetail.jsp?view=3" in text
    assert "#COMPASS" in text


@pytest.fixture
def compass_env(initialized_db, monkeypatch):
    monkeypatch.setattr(orchestrator.config, "DB_PATH", initialized_db)
    monkeypatch.setattr(orchestrator, "fetch_compass_files", lambda: list(_FILES))
    monkeypatch.setattr(orchestrator, "_SEND_PAUSE_SECONDS", 0)
    sent = []

    async def fake_send(chat_id, text):
        sent.append(text)
        return len(sent)

    monkeypatch.setattr(orchestrator, "send_message", fake_send)
    return sent


async def test_new_files_are_posted_oldest_first_once(compass_env):
    sent = compass_env

    await orchestrator._process_compass_files(["chat"])
    await orchestrator._process_compass_files(["chat"])

    assert len(sent) == 2
    assert "deck 10 01.pptx" in sent[0]
    assert "deck &lt;10 05&gt;.pptx" in sent[1]


async def test_prefill_suppresses_existing_files(compass_env):
    sent = compass_env

    assert orchestrator.prefill_compass_files() == 2
    assert get_compass_files_needing_post() == []

    await orchestrator._process_compass_files(["chat"])
    assert sent == []


def test_prefill_raises_when_fetch_fails(initialized_db, monkeypatch):
    monkeypatch.setattr(orchestrator.config, "DB_PATH", initialized_db)
    monkeypatch.setattr(orchestrator, "fetch_compass_files", lambda: None)

    with pytest.raises(RuntimeError):
        orchestrator.prefill_compass_files()
