"""Telegram API transport layer.

This module owns all Telegram API interaction: sending photos and messages to
the single configured channel.

Design constraints:
    - Uses a lazy import for ``telegram`` (python-telegram-bot) so this module
      can be imported without the package installed.
    - Imports configuration from ``core.config`` (bot token, channel id). Does
      NOT import formatting or data-fetching modules.
    - Send operations return ``False`` / ``None`` on failure rather than
      raising, so the orchestrator loop is never crashed by a transient error.
"""

from __future__ import annotations

import asyncio
import warnings
from typing import Optional

from starship_notam.core import config
from starship_notam.core.logging import logger

# Cache for the lazily-constructed Bot instance so we don't rebuild it per call.
_BOT = None

# Total attempts per send, and the wait (seconds) before each retry after a
# timeout. A flood-control error (RetryAfter) waits as long as Telegram asks.
_MAX_ATTEMPTS = 3
_TIMEOUT_BACKOFF = (2, 5)


def _get_bot():
    """Lazily construct and cache the python-telegram-bot ``Bot`` instance."""
    global _BOT
    if _BOT is None:
        from telegram import Bot  # lazy import

        _BOT = Bot(token=config.TELEGRAM_BOT_TOKEN)
    return _BOT


def _retry_after_seconds(error) -> float:
    """Return a RetryAfter delay in seconds.

    PTB 22 returns an int (deprecated) or a timedelta depending on the
    ``PTB_TIMEDELTA`` setting; both are handled, so the warning is silenced.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        retry_after = error.retry_after
    if hasattr(retry_after, "total_seconds"):
        return retry_after.total_seconds()
    return float(retry_after)


async def _send_with_retries(send, description: str):
    """Await ``send()`` with a bounded number of retries.

    Retries only on ``TimedOut`` (with :data:`_TIMEOUT_BACKOFF` waits) and
    ``RetryAfter`` (waiting as long as Telegram asks), up to
    :data:`_MAX_ATTEMPTS` attempts in total. Any other exception, or the last
    retryable one, is raised to the caller.

    Note that a timed-out request may still have been delivered, so a retry
    can occasionally duplicate a post; this matches the previous behaviour.
    """
    from telegram.error import RetryAfter, TimedOut  # lazy import

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            return await send()
        except RetryAfter as e:
            if attempt == _MAX_ATTEMPTS:
                raise
            delay = _retry_after_seconds(e)
            logger.warning(
                f"Flood control while sending {description}; retrying in "
                f"{delay:.0f}s (attempt {attempt}/{_MAX_ATTEMPTS})"
            )
        except TimedOut:
            if attempt == _MAX_ATTEMPTS:
                raise
            delay = _TIMEOUT_BACKOFF[min(attempt, len(_TIMEOUT_BACKOFF)) - 1]
            logger.warning(
                f"Timed out sending {description}; retrying in {delay}s "
                f"(attempt {attempt}/{_MAX_ATTEMPTS})"
            )
        await asyncio.sleep(delay)


# --- Send operations --------------------------------------------------------


async def send_photo(
    chat_id: str, photo_path: str, caption: Optional[str] = None
) -> bool:
    """Send a photo with an optional HTML caption to a chat.

    Returns ``True`` on success, ``False`` on failure (including when the bot
    lacks access to the chat / channel — HTTP 403 Forbidden). Timeouts and
    flood-control errors are retried a bounded number of times.
    """
    from telegram import InputFile  # lazy import
    from telegram.error import Forbidden  # lazy import

    async def send():
        # Reopen the file on every attempt: a failed upload consumes it.
        with open(photo_path, "rb") as fh:
            await _get_bot().send_photo(
                chat_id=chat_id,
                photo=InputFile(fh),
                caption=caption,
                parse_mode="HTML",
            )

    try:
        logger.info(f'Caption text: {caption if caption else "(no caption)"}')
        await _send_with_retries(send, f"photo {photo_path} to {chat_id}")
        return True
    except Forbidden:
        logger.warning(
            f"Failed to send photo {photo_path} to {chat_id}: bot lacks access "
            f"(is it an admin of the channel?)"
        )
        return False
    except Exception as e:
        logger.exception(
            f"Failed to send photo {photo_path} via python-telegram-bot to {chat_id}: {e}"
        )
        return False


async def send_message(chat_id: str, text: str) -> Optional[int]:
    """Send an HTML text message to a chat.

    Returns the sent ``message_id`` on success, or ``None`` on failure,
    including when the bot is blocked (Forbidden). Timeouts and flood-control
    errors are retried a bounded number of times.
    """
    from telegram.error import Forbidden  # lazy import

    async def send():
        return await _get_bot().send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    try:
        message = await _send_with_retries(send, f"message to {chat_id}")
        return message.message_id
    except Forbidden:
        logger.warning(f"Bot blocked in chat {chat_id}")
        return None
    except Exception as e:
        logger.exception(f"Failed to send message to {chat_id}: {e}")
        return None
