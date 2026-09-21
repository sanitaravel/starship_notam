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
from typing import Optional

from starship_notam.core import config
from starship_notam.core.logging import logger

# Cache for the lazily-constructed Bot instance so we don't rebuild it per call.
_BOT = None


def _get_bot():
    """Lazily construct and cache the python-telegram-bot ``Bot`` instance."""
    global _BOT
    if _BOT is None:
        from telegram import Bot  # lazy import

        _BOT = Bot(token=config.TELEGRAM_BOT_TOKEN)
    return _BOT


# --- Send operations --------------------------------------------------------


async def send_photo(
    chat_id: str, photo_path: str, caption: Optional[str] = None
) -> bool:
    """Send a photo with an optional HTML caption to a chat.

    Returns ``True`` on success, ``False`` on failure (including when the bot
    lacks access to the chat / channel — HTTP 403 Forbidden).
    """
    from telegram import InputFile  # lazy import
    from telegram.error import Forbidden  # lazy import

    try:
        bot = _get_bot()
        with open(photo_path, "rb") as fh:
            input_file = InputFile(fh)
            logger.info(f'Caption text: {caption if caption else "(no caption)"}')
            await bot.send_photo(
                chat_id=chat_id,
                photo=input_file,
                caption=caption,
                parse_mode="HTML",
            )
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

    Returns the sent ``message_id`` on success, or ``None`` on failure. Retries
    on transient timeouts; returns ``None`` if the bot is blocked (Forbidden).
    """
    import telegram  # lazy import
    from telegram.error import Forbidden  # lazy import

    while True:
        try:
            bot = _get_bot()
            message = await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            return message.message_id
        except Forbidden:
            logger.warning(f"Bot blocked in chat {chat_id}")
            return None
        except telegram.error.TimedOut:
            logger.warning(f"Failed to send message to {chat_id}: Timed out")
        except Exception as e:
            logger.exception(f"Failed to send message to {chat_id}: {e}")
            return None
