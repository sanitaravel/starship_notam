"""FCC ELS experimental-license applications."""

from __future__ import annotations

import asyncio

from starship_notam.bot.formatting import format_fcc_els_application
from starship_notam.bot.orchestrator.posting import post_pending
from starship_notam.core import config
from starship_notam.core.logging import logger
from starship_notam.data import (
    get_fcc_els_applications_needing_post,
    mark_fcc_els_application_posted,
    save_fcc_els_application,
)
from starship_notam.scrapers import fetch_fcc_els_applications


async def process_fcc_els_applications(chat_list: list[str]) -> None:
    """Fetch FCC ELS applications, persist them, and post any needing posting."""
    logger.info("Refreshing FCC ELS applications needing Telegram post")
    try:
        logger.info("Getting FCC ELS applications")
        apps = await asyncio.to_thread(fetch_fcc_els_applications)
        for app in apps or []:
            try:
                save_fcc_els_application(app, config.DB_PATH)
            except Exception:
                logger.exception(f"Failed to save FCC ELS application {app}")
    except Exception:
        logger.exception("Failed to fetch and parse FCC ELS applications")

    await post_pending(
        get_fcc_els_applications_needing_post(config.DB_PATH),
        chat_list,
        label="FCC ELS application",
        format_fn=format_fcc_els_application,
        key_fn=lambda a: a["file_number"],
        mark_fn=lambda key, ids: mark_fcc_els_application_posted(key, ids, config.DB_PATH),
    )
