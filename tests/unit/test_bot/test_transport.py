"""Telegram sends retry a bounded number of times.

Regression test for fix-plan step 5: ``send_message`` used to retry forever
on ``TimedOut`` with no wait, and ``send_photo`` did not retry at all.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from telegram.error import BadRequest, Forbidden, RetryAfter, TimedOut

from starship_notam.bot import transport


class FakeBot:
    """Raises the queued errors in order, then succeeds."""

    def __init__(self, *errors):
        self.errors = list(errors)
        self.calls = 0

    async def _call(self):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return SimpleNamespace(message_id=42)

    async def send_message(self, **kwargs):
        return await self._call()

    async def send_photo(self, **kwargs):
        kwargs["photo"].input_file_content  # the file must be readable
        return await self._call()


@pytest.fixture
def sleeps(monkeypatch):
    waited: list[float] = []

    async def fake_sleep(seconds):
        waited.append(seconds)

    monkeypatch.setattr(transport.asyncio, "sleep", fake_sleep)
    return waited


def _use(monkeypatch, bot):
    monkeypatch.setattr(transport, "_get_bot", lambda: bot)
    return bot


async def test_message_gives_up_after_max_attempts(monkeypatch, sleeps):
    bot = _use(monkeypatch, FakeBot(*[TimedOut()] * 10))

    assert await transport.send_message("chat", "hi") is None
    assert bot.calls == transport._MAX_ATTEMPTS
    assert sleeps == list(transport._TIMEOUT_BACKOFF)


async def test_message_succeeds_after_a_timeout(monkeypatch, sleeps):
    bot = _use(monkeypatch, FakeBot(TimedOut()))

    assert await transport.send_message("chat", "hi") == 42
    assert bot.calls == 2
    assert sleeps == [transport._TIMEOUT_BACKOFF[0]]


@pytest.mark.parametrize("retry_after", [7, timedelta(seconds=7)])
async def test_message_waits_as_long_as_flood_control_asks(
    monkeypatch, sleeps, retry_after
):
    _use(monkeypatch, FakeBot(RetryAfter(retry_after)))

    assert await transport.send_message("chat", "hi") == 42
    assert sleeps == [7.0]


async def test_message_does_not_retry_other_errors(monkeypatch, sleeps):
    bot = _use(monkeypatch, FakeBot(BadRequest("can't parse entities")))

    assert await transport.send_message("chat", "hi") is None
    assert bot.calls == 1
    assert sleeps == []


async def test_message_forbidden_returns_none(monkeypatch, sleeps):
    bot = _use(monkeypatch, FakeBot(Forbidden("bot was kicked")))

    assert await transport.send_message("chat", "hi") is None
    assert bot.calls == 1


async def test_photo_retries_timeouts_and_reopens_the_file(
    monkeypatch, sleeps, tmp_path
):
    photo = tmp_path / "map.png"
    photo.write_bytes(b"\x89PNG fake")
    bot = _use(monkeypatch, FakeBot(TimedOut(), TimedOut()))

    assert await transport.send_photo("chat", str(photo), caption="c") is True
    assert bot.calls == 3


async def test_photo_gives_up_after_max_attempts(monkeypatch, sleeps, tmp_path):
    photo = tmp_path / "map.png"
    photo.write_bytes(b"\x89PNG fake")
    bot = _use(monkeypatch, FakeBot(*[TimedOut()] * 10))

    assert await transport.send_photo("chat", str(photo)) is False
    assert bot.calls == transport._MAX_ATTEMPTS
