"""Telegram API transport layer.

This module owns all Telegram API interaction: sending photos and messages,
and discovering/persisting the set of chats the bot participates in.

Design constraints:
    - Uses a lazy import for ``telegram`` (python-telegram-bot) so this module
      can be imported without the package installed.
    - Imports configuration from ``core.config`` (bot token, chat ids, state
      path). Does NOT import formatting or data-fetching modules.
    - Send operations return ``False`` / ``None`` on failure rather than
      raising, so the orchestrator loop is never crashed by a transient error.
    - Chats that block the bot (HTTP 403 / Forbidden) are removed from the
      persisted state.
"""

from __future__ import annotations

import asyncio
import json
import os
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


# --- Persisted chat state ---------------------------------------------------


def _load_state() -> dict:
    try:
        if os.path.exists(config.STATE_PATH):
            with open(config.STATE_PATH, "r", encoding="utf-8") as fh:
                return json.load(fh)
    except Exception:
        logger.exception("Failed to load Telegram chats state")
    return {"chats": [], "last_update_id": None}


def _save_state(state: dict) -> None:
    try:
        with open(config.STATE_PATH, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
    except Exception:
        logger.exception("Failed to save Telegram chats state")


def _get_combined_chat_ids() -> list[str]:
    """Union of persisted chats and env-provided ``CHAT_IDS`` (order-preserving)."""
    state = _load_state()
    persisted = [str(c) for c in state.get("chats", [])]
    return list(dict.fromkeys(persisted + config.CHAT_IDS))


def _remove_blocked_chat(chat_id: str) -> None:
    """Remove a chat that blocked the bot from persisted state."""
    try:
        state = _load_state()
        persisted = [str(c) for c in state.get("chats", [])]
        if str(chat_id) in persisted:
            state["chats"] = [c for c in persisted if c != str(chat_id)]
            _save_state(state)
            logger.info(
                f"Removed blocked chat {chat_id} from persisted Telegram state"
            )
        else:
            logger.info(
                f"Chat {chat_id} blocked the bot (not present in persisted state)"
            )
    except Exception:
        logger.exception(
            "Failed to update persisted Telegram state after Forbidden error"
        )


# --- Send operations --------------------------------------------------------


async def send_photo(
    chat_id: str, photo_path: str, caption: Optional[str] = None
) -> bool:
    """Send a photo with an optional HTML caption to a chat.

    Returns ``True`` on success, ``False`` on failure. If the bot is blocked by
    the chat (Forbidden), the chat is removed from the persisted state.
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
        _remove_blocked_chat(chat_id)
        logger.warning(
            f"Failed to send photo {photo_path} to {chat_id}: bot was blocked by the user"
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


# --- Chat discovery ---------------------------------------------------------


async def refresh_known_chats() -> list[str]:
    """Fetch recent updates and persist any new chat IDs the bot sees.

    Uses ``getUpdates`` to discover chats the bot is in. It stores discovered
    chat ids and the last processed update id to avoid re-processing the same
    updates repeatedly. Returns the combined list of persisted + env chat ids.
    """
    import telegram  # lazy import

    state = _load_state()
    last_update_id = state.get("last_update_id")
    bot = _get_bot()
    try:
        offset = (last_update_id + 1) if (last_update_id is not None) else None
        updates = None
        while updates is None:
            try:
                updates = await bot.get_updates(timeout=30, offset=offset)
            except telegram.error.TimedOut:
                logger.warning("get_updates timed out; retrying")
                await asyncio.sleep(5)
            except Exception:
                logger.exception("Failed to get_updates from Telegram bot")
                return _get_combined_chat_ids()
        if not updates:
            return _get_combined_chat_ids()

        new_chats = set(str(c) for c in state.get("chats", []))
        max_update = last_update_id if last_update_id is not None else -1
        for upd in updates:
            try:
                msg = getattr(upd, "message", None) or getattr(
                    upd, "edited_message", None
                )
                if msg and getattr(msg, "chat", None):
                    new_chats.add(str(msg.chat.id))
                if hasattr(upd, "update_id") and upd.update_id is not None:
                    if upd.update_id > max_update:
                        max_update = upd.update_id
            except Exception:
                logger.exception("Failed to parse update while refreshing chats")

        state["chats"] = list(new_chats)
        if max_update >= 0:
            state["last_update_id"] = max_update
        _save_state(state)
    except Exception:
        logger.exception("Failed to refresh known Telegram chats via get_updates")
    return _get_combined_chat_ids()
