"""FAA planned activities and the FAA DRS launch license."""

from __future__ import annotations

import asyncio

from src.bot.formatting import format_faa_activity, format_faa_license
from src.bot.orchestrator.posting import post_pending
from src.core import config
from src.core.logging import logger
from src.data import (
    faa_activities,
    faa_licenses,
)
from src.scrapers import faa_advisory_fetcher, fetch_faa_license


async def process_faa_activities(chat_list: list[str]) -> None:
    """Fetch FAA advisories, persist them, and post any that need posting."""
    logger.info("Refreshing FAA activities needing Telegram post")
    try:
        logger.info("Getting FAA activities")
        activities = await asyncio.to_thread(faa_advisory_fetcher.fetch)
        for activity in activities or []:
            try:
                faa_activities.save(activity, config.DB_PATH)
            except Exception:
                logger.exception(f"Failed to save FAA activity {activity}")
    except Exception:
        logger.exception("Failed to fetch and parse FAA advisory")

    await post_pending(
        faa_activities.needing_post(config.DB_PATH),
        chat_list,
        label="FAA activity",
        format_fn=format_faa_activity,
        key_fn=lambda a: a["mission"],
        mark_fn=lambda key, ids: faa_activities.mark_posted(key, ids, config.DB_PATH),
    )


async def process_faa_licenses(chat_list: list[str]) -> None:
    """Fetch the FAA DRS launch license, persist it, and post any changes.

    The (blocking) fetch is offloaded to a worker thread; the
    record is persisted through the data layer (which performs SHA-256 change
    detection and re-flags changed records for posting).
    """
    logger.info("Refreshing FAA DRS launch license needing Telegram post")
    try:
        logger.info("Getting FAA DRS launch license")
        record = await asyncio.to_thread(fetch_faa_license)
        if record:
            try:
                faa_licenses.save(record, config.DB_PATH)
            except Exception:
                logger.exception(f"Failed to save FAA DRS license {record}")
    except Exception:
        logger.exception("Failed to fetch and parse FAA DRS launch license")

    await post_pending(
        faa_licenses.needing_post(config.DB_PATH),
        chat_list,
        label="FAA DRS license",
        format_fn=format_faa_license,
        key_fn=lambda lic: lic["doc_unique_id"],
        mark_fn=lambda key, ids: faa_licenses.mark_posted(key, ids, config.DB_PATH),
    )
