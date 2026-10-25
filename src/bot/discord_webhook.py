"""Discord webhook transport: post messages and photos to a Discord channel.

The bot posts to Discord through a channel webhook, so it needs no gateway
connection or bot account. Messages arrive as the Telegram HTML built by
``bot.formatting`` and are converted with ``bot.discord_markdown``.

Design constraints:
    - ``httpx`` is imported lazily inside the send functions.
    - The webhook URL carries the webhook's secret token, so it is never
      logged: :class:`DiscordWebhook` prints only the webhook id, and errors
      are logged by type and status code, not by their text.
    - Send operations return ``None`` on failure rather than raising, like
      the Telegram transport.

Public API:
    DiscordWebhook(url)
    async send_message(webhook, text) -> str | None
    async send_photo(webhook, photo_path, caption) -> str | None
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlsplit

from src.bot.discord_markdown import split_message, to_discord_markdown
from src.core.logging import logger

# Discord's limit for a message's content.
_CONTENT_LIMIT = 2000

# SUPPRESS_EMBEDS: no link previews, like disable_web_page_preview on Telegram.
_FLAGS = 1 << 2

# Source text must never ping @everyone, a role or a user.
_NO_MENTIONS = {"parse": []}

# Total attempts per request, and the wait (seconds) before each retry after a
# timeout or server error. A rate limit (HTTP 429) waits as long as Discord asks.
_MAX_ATTEMPTS = 3
_RETRY_BACKOFF = (2, 5)
_TIMEOUT_SECONDS = 30

# Prefix for the ids stored with a posted item, so they can be told apart
# from Telegram message ids in the same column.
_ID_PREFIX = "discord:"


@dataclass(frozen=True)
class DiscordWebhook:
    """A Discord channel webhook; prints as its id, never its token."""

    url: str = field(repr=False)

    def __str__(self) -> str:
        parts = urlsplit(self.url).path.rstrip("/").split("/")
        webhook_id = parts[-2] if len(parts) >= 2 else "?"
        return f"Discord webhook {webhook_id}"

    __repr__ = __str__


class _RetryableError(Exception):
    """A server error or rate limit worth retrying after ``delay`` seconds."""

    def __init__(self, reason: str, delay: float):
        super().__init__(reason)
        self.reason = reason
        self.delay = delay


class DiscordError(Exception):
    """Discord rejected a request (HTTP status ``status``)."""

    def __init__(self, status: int):
        super().__init__(f"HTTP {status}")
        self.status = status


def _rate_limit_delay(response) -> float:
    """Seconds to wait after a 429, from the JSON body or the Retry-After header."""
    try:
        return float(response.json()["retry_after"])
    except Exception:
        try:
            return float(response.headers.get("Retry-After", 1))
        except ValueError:
            return 1.0


async def _post(webhook: DiscordWebhook, description: str, **request) -> dict:
    """POST to the webhook with bounded retries; return the created message.

    Retries timeouts, connection errors and 5xx responses (with
    :data:`_RETRY_BACKOFF` waits) and 429 rate limits (waiting as long as
    Discord asks), up to :data:`_MAX_ATTEMPTS` attempts. Any other error
    response raises :class:`DiscordError`. Like the Telegram transport, a
    timed-out request may still have been delivered, so a retry can
    occasionally duplicate a post.
    """
    import httpx  # lazy import

    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            backoff = _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF)) - 1]
            try:
                # wait=true makes Discord return the message it created.
                response = await client.post(webhook.url, params={"wait": "true"}, **request)
                if response.status_code == 429:
                    raise _RetryableError("rate limited", _rate_limit_delay(response))
                if response.status_code >= 500:
                    raise _RetryableError(f"HTTP {response.status_code}", backoff)
                if response.status_code >= 400:
                    raise DiscordError(response.status_code)
                return response.json()
            except (httpx.TimeoutException, httpx.TransportError) as e:
                error = _RetryableError(type(e).__name__, backoff)
            except _RetryableError as e:
                error = e
            if attempt == _MAX_ATTEMPTS:
                raise error
            logger.warning(
                f"{error.reason} sending {description} to {webhook}; retrying in "
                f"{error.delay:.0f}s (attempt {attempt}/{_MAX_ATTEMPTS})"
            )
            await asyncio.sleep(error.delay)


def _payload(content: str) -> dict:
    return {"content": content, "flags": _FLAGS, "allowed_mentions": _NO_MENTIONS}


async def _send_chunks(
    webhook: DiscordWebhook, chunks: list[str], description: str, first=None
) -> Optional[str]:
    """Send *chunks* in order; return the first message's prefixed id.

    ``first``, when given, sends the first chunk instead (to attach a photo).
    Chunks after a failed one are not sent, and the post counts as sent when
    its first message went out.
    """
    message_id = None
    for i, chunk in enumerate(chunks):
        try:
            if i == 0 and first is not None:
                message = await first(chunk)
            else:
                message = await _post(webhook, description, json=_payload(chunk))
        except DiscordError as e:
            hint = " (was the webhook deleted?)" if e.status in (401, 403, 404) else ""
            logger.warning(f"Discord rejected {description} to {webhook}: HTTP {e.status}{hint}")
            break
        except Exception as e:
            logger.error(f"Failed to send {description} to {webhook}: {type(e).__name__}")
            break
        if message_id is None:
            message_id = f"{_ID_PREFIX}{message.get('id')}"
    return message_id


async def send_message(webhook: DiscordWebhook, text: str) -> Optional[str]:
    """Send an HTML message (converted to markdown) to a Discord webhook.

    A message over Discord's 2000-character limit goes out as several
    messages, split between paragraphs. Returns ``"discord:<message id>"`` of
    the first one, or ``None`` on failure.
    """
    chunks = split_message(to_discord_markdown(text), _CONTENT_LIMIT) or [""]
    return await _send_chunks(webhook, chunks, "message")


async def send_photo(
    webhook: DiscordWebhook, photo_path: str, caption: Optional[str] = None
) -> Optional[str]:
    """Send a photo with an optional HTML caption to a Discord webhook.

    The caption goes in the photo's message; any part over the
    2000-character limit follows as separate messages. Returns
    ``"discord:<message id>"`` of the photo message, or ``None`` on failure.
    """
    chunks = split_message(to_discord_markdown(caption or ""), _CONTENT_LIMIT) or [""]
    description = f"photo {os.path.basename(photo_path)}"

    async def send_with_photo(content: str) -> dict:
        # Read once: unlike a file handle, bytes can be re-sent on a retry.
        with open(photo_path, "rb") as fh:
            data = fh.read()
        return await _post(
            webhook,
            description,
            data={"payload_json": json.dumps(_payload(content))},
            files={"files[0]": (os.path.basename(photo_path), data, "image/png")},
        )

    return await _send_chunks(webhook, chunks, description, first=send_with_photo)
