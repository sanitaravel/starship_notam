"""FCC ELS experimental-license applications."""

from __future__ import annotations

import asyncio

from src.bot.formatting import format_fcc_els_application
from src.bot.orchestrator.posting import post_pending
from src.core import config
from src.core.logging import logger
from src.data import fcc_els_applications
from src.scrapers import fetch_fcc_els_applications


async def process_fcc_els_applications(chat_list: list[str]) -> None:
    """Fetch FCC ELS applications, persist them, and post any needing posting."""
    logger.info("Refreshing FCC ELS applications needing Telegram post")
    try:
        logger.info("Getting FCC ELS applications")
        apps = await asyncio.to_thread(fetch_fcc_els_applications)
        for app in apps or []:
            try:
                fcc_els_applications.save(app, config.DB_PATH)
            except Exception:
                logger.exception(f"Failed to save FCC ELS application {app}")
    except Exception:
        logger.exception("Failed to fetch and parse FCC ELS applications")

    await post_pending(
        fcc_els_applications.needing_post(config.DB_PATH),
        chat_list,
        label="FCC ELS application",
        format_fn=format_fcc_els_application,
        key_fn=lambda a: a["file_number"],
        mark_fn=lambda key, ids: fcc_els_applications.mark_posted(key, ids, config.DB_PATH),
    )
