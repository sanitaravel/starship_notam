"""Discord webhook sends: payload, retries, splitting and token hygiene."""

from __future__ import annotations

import json
from functools import partial

import httpx
import pytest

from src.bot import discord_webhook, transport
from src.bot.discord_webhook import DiscordWebhook

URL = "https://discord.com/api/webhooks/123456/s3cr3t-token"
WEBHOOK = DiscordWebhook(URL)


class FakeDiscord:
    """Answers queued (status, body) pairs in order, then 200 with a message."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.responses:
            status, body = self.responses.pop(0)
            return httpx.Response(status, json=body)
        return httpx.Response(200, json={"id": str(900 + len(self.requests))})


@pytest.fixture
def sleeps(monkeypatch):
    waited: list[float] = []

    async def fake_sleep(seconds):
        waited.append(seconds)

    monkeypatch.setattr(discord_webhook.asyncio, "sleep", fake_sleep)
    return waited


def _use(monkeypatch, server: FakeDiscord) -> FakeDiscord:
    client = partial(httpx.AsyncClient, transport=httpx.MockTransport(server))
    monkeypatch.setattr(httpx, "AsyncClient", client)
    return server


def test_webhook_never_prints_its_token():
    assert str(WEBHOOK) == "Discord webhook 123456"
    assert "s3cr3t" not in repr(WEBHOOK)
    assert "s3cr3t" not in f"{[WEBHOOK]}"


async def test_message_is_markdown_without_previews_or_pings(monkeypatch, sleeps):
    server = _use(monkeypatch, FakeDiscord())

    result = await discord_webhook.send_message(WEBHOOK, "<b>Новый</b> @everyone")

    assert result == "discord:901"
    (request,) = server.requests
    assert request.url.params["wait"] == "true"
    body = json.loads(request.content)
    assert body == {
        "content": "**Новый** @everyone",
        "flags": 4,
        "allowed_mentions": {"parse": []},
    }


async def test_rate_limit_waits_as_long_as_discord_asks(monkeypatch, sleeps):
    server = _use(monkeypatch, FakeDiscord((429, {"retry_after": 1.5})))

    assert await discord_webhook.send_message(WEBHOOK, "hi") == "discord:902"
    assert len(server.requests) == 2
    assert sleeps == [1.5]


async def test_server_errors_give_up_after_max_attempts(monkeypatch, sleeps):
    server = _use(monkeypatch, FakeDiscord(*[(502, {})] * 10))

    assert await discord_webhook.send_message(WEBHOOK, "hi") is None
    assert len(server.requests) == discord_webhook._MAX_ATTEMPTS
    assert sleeps == list(discord_webhook._RETRY_BACKOFF)


async def test_client_errors_are_not_retried(monkeypatch, sleeps):
    server = _use(monkeypatch, FakeDiscord((404, {"message": "Unknown Webhook"})))

    assert await discord_webhook.send_message(WEBHOOK, "hi") is None
    assert len(server.requests) == 1
    assert sleeps == []


async def test_errors_are_logged_without_the_token(monkeypatch, sleeps):
    logged: list[str] = []
    monkeypatch.setattr(discord_webhook.logger, "warning", logged.append)
    monkeypatch.setattr(discord_webhook.logger, "error", logged.append)

    def refuse(request):
        raise httpx.ConnectError(f"cannot reach {request.url}")

    _use(monkeypatch, refuse)

    assert await discord_webhook.send_message(WEBHOOK, "hi") is None
    assert logged
    assert not any("s3cr3t" in line for line in logged)


async def test_long_message_is_split(monkeypatch, sleeps):
    server = _use(monkeypatch, FakeDiscord())
    text = "\n\n".join(["a" * 1500, "b" * 1500])

    assert await discord_webhook.send_message(WEBHOOK, text) == "discord:901"
    contents = [json.loads(r.content)["content"] for r in server.requests]
    assert contents == ["a" * 1500, "b" * 1500]


async def test_photo_is_attached_with_its_caption(monkeypatch, sleeps, tmp_path):
    photo = tmp_path / "map.png"
    photo.write_bytes(b"\x89PNG fake")
    server = _use(monkeypatch, FakeDiscord((503, {})))

    result = await discord_webhook.send_photo(WEBHOOK, str(photo), caption="<b>NOTAM</b>")

    assert result == "discord:902"
    request = server.requests[-1]
    body = request.content
    assert b'filename="map.png"' in body
    assert b"\x89PNG fake" in body
    assert b'"content": "**NOTAM**"' in body


async def test_transport_routes_webhooks_to_discord(monkeypatch):
    sent = []

    async def fake_message(webhook, text):
        sent.append(("message", webhook, text))
        return "discord:1"

    async def fake_photo(webhook, path, caption):
        sent.append(("photo", webhook, path, caption))
        return "discord:2"

    monkeypatch.setattr(discord_webhook, "send_message", fake_message)
    monkeypatch.setattr(discord_webhook, "send_photo", fake_photo)

    assert await transport.send_message(WEBHOOK, "t") == "discord:1"
    assert await transport.send_photo(WEBHOOK, "p.png", caption="c") == "discord:2"
    assert sent == [("message", WEBHOOK, "t"), ("photo", WEBHOOK, "p.png", "c")]
