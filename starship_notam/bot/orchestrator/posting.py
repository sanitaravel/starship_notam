"""Send pending items to Telegram and mark them posted."""

from __future__ import annotations

import asyncio

from starship_notam.bot.orchestrator import shutdown
from starship_notam.bot.transport import send_message
from starship_notam.core.logging import logger


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
) -> None:
    """Send each pending item to every chat and mark it posted on success.

    ``format_fn(item)`` builds the message text, ``key_fn(item)`` returns the
    item's identifier and ``mark_fn(key, message_ids)`` records the post.
    An item is marked posted only when at least one send succeeded; otherwise
    it stays pending and is retried on the next cycle.
    """
    if not items:
        logger.info(f"No {label} needing Telegram post at this time")
        return

    logger.info(f"Found {len(items)} {label} needing post to Telegram")
    for item in items:
        if shutdown.stopping():
            logger.info(f"Stop requested; leaving the remaining {label} for the next start")
            return
        key = key_fn(item)
        try:
            text = format_fn(item)

            message_ids = []
            for chat_id in chat_list:
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
