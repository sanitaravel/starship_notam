"""Convenience entry point for the Starship NOTAM Telegram bot.

Running ``python main.py`` from the project root is equivalent to invoking the
package module form ``python -m starship_notam``. It provides the same behavior
as the legacy ``python telegram_bot.py`` invocation did.

This script is intentionally thin: it does not initialize the database, refresh
Telegram chats, or run any scheduling logic itself. That full startup sequence
is owned by :func:`starship_notam.bot.orchestrator.main_loop`, which is driven
by the ``main`` function in :mod:`starship_notam.__main__`. This module simply
delegates to that existing entry point so there is a single source of truth for
application startup.
"""

from __future__ import annotations

from starship_notam.__main__ import main

if __name__ == "__main__":
    main()
