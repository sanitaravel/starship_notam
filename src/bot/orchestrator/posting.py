"""Send pending items to Telegram and mark them posted."""

from __future__ import annotations

import asyncio
import os

from src.bot.orchestrator import shutdown
from src.bot.transport import send_message, send_photo
from src.core.logging import logger


# Pause after each Telegram send to stay clear of rate limits.
_SEND_PAUSE_SECONDS = 5


async def post_pending(
    items: list[dict],
    chat_list: list[str],
    *,
    label: str,
    format_fn,
    key_fn,
    mark_fn,
    photo_fn=None,
) -> None:
    """Send each pending item to every chat and mark it posted on success.

    ``format_fn(item)`` builds the message text, ``key_fn(item)`` returns the
    item's identifier and ``mark_fn(key, message_ids)`` records the post.
    An item is marked posted only when at least one send succeeded; otherwise
    it stays pending and is retried on the next cycle.

    ``photo_fn(item)``, when given, is a blocking call (run in a thread) that
    renders a picture for the item and returns its path, or None to send
    plain text. The text then goes out as the photo's caption, so it must fit
    Telegram's 1024-character caption limit. The file is deleted afterwards.
    """
    if not items:
        logger.info(f"No {label} needing a post at this time")
        return

    logger.info(f"Found {len(items)} {label} needing a post")
    for item in items:
        if shutdown.stopping():
            logger.info(f"Stop requested; leaving the remaining {label} for the next start")
            return
        key = key_fn(item)
        photo = None
        try:
            text = format_fn(item)
            if photo_fn:
                photo = await asyncio.to_thread(photo_fn, item)

            message_ids = []
            for chat_id in chat_list:
                if photo:
                    message_id = await send_photo(chat_id, photo, caption=text)
                else:
                    message_id = await send_message(chat_id, text)
                if message_id:
                    logger.info(f"Sent {label} {key} to chat {chat_id}")
                    message_ids.append(message_id)
                else:
                    logger.warning(f"Failed to send {label} {key} to chat {chat_id}")
                await asyncio.sleep(_SEND_PAUSE_SECONDS)

            if not message_ids:
                logger.error(
                    f"Failed to send {label} {key} to any configured chat; "
                    "keeping unposted for retry"
                )
                continue

            logger.info(f"Marking {label} {key} as posted")
            try:
                mark_fn(key, ",".join(str(mid) for mid in message_ids))
            except Exception:
                logger.exception(f"Failed to mark {label} {key} as posted")

        except Exception:
            logger.exception(f"Failed to send {label} {key}")
        finally:
            if photo:
                try:
                    os.remove(photo)
                except OSError:
                    logger.exception(f"Failed to delete image {photo}")
