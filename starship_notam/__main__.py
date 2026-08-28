"""Executable entry point for the Starship NOTAM Telegram bot.

Enables invocation via ``python -m starship_notam``. This module is a thin
wrapper around :func:`starship_notam.bot.orchestrator.main_loop`, which is the
top-level coroutine that drives the whole application.

``main_loop`` already performs the full startup sequence:

    1. ``ensure_setup()`` validates ``TELEGRAM_BOT_TOKEN`` and initializes the
       database schema via ``data.connection.init_db(config.DB_PATH)``.
    2. ``bot.transport.refresh_known_chats()`` discovers the chats the bot has
       been added to.
    3. Startup messages are sent and the scheduled monitoring loop begins,
       repeatedly calling ``generate_and_send()`` and sleeping until the next
       scheduled run.

Because ``main_loop`` owns that sequence, this entry point intentionally does
not duplicate database initialization or chat refresh; doing so would run those
steps twice. It simply runs the loop under ``asyncio.run`` and handles
``KeyboardInterrupt`` for a clean shutdown.
"""

from __future__ import annotations

import asyncio

from starship_notam.bot.orchestrator import main_loop
from starship_notam.core.logging import logger


def main() -> None:
    """Run the bot's main loop until interrupted.

    Delegates the full startup sequence (database initialization, chat refresh,
    startup announcements, and the scheduled monitoring loop) to
    ``bot.orchestrator.main_loop``. A ``KeyboardInterrupt`` (Ctrl-C) results in
    a clean, logged shutdown rather than a traceback.
    """
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        logger.info("Telegram NOTAM bot stopped by user (KeyboardInterrupt)")


if __name__ == "__main__":
    main()
