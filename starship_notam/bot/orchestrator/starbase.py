"""Starbase beach-closure and road-delay alerts."""

from __future__ import annotations

import asyncio

from starship_notam.bot.formatting import format_beach_alert, format_road_alert
from starship_notam.bot.orchestrator.posting import post_pending
from starship_notam.core import config
from starship_notam.core.logging import logger
from starship_notam.data import (
    get_beach_alerts_needing_post,
    get_road_alerts_needing_post,
    mark_beach_posted,
    mark_road_posted,
    save_beach_alert,
    save_road_alert,
)
from starship_notam.scrapers import fetch_starbase_status


async def ingest_starbase_alerts() -> None:
    """Fetch Starbase status and persist beach/road alerts."""
    logger.info("Refreshing Starbase alerts needing Telegram post")
    try:
        logger.info("Fetching Starbase status")
        data = await asyncio.to_thread(fetch_starbase_status)
        # ingest into DB
        if data.get("beach"):
            save_beach_alert(data["beach"], config.DB_PATH)
        for r in data.get("road_delays", []):
            save_road_alert(r, config.DB_PATH)
    except Exception:
        logger.exception("Failed to fetch and parse Starbase alerts")


async def process_beach_alerts(chat_list: list[str]) -> None:
    """Post beach alerts that still need posting."""
    await post_pending(
        get_beach_alerts_needing_post(config.DB_PATH),
        chat_list,
        label="beach alert",
        format_fn=format_beach_alert,
        key_fn=lambda a: a["alert_key"],
        mark_fn=lambda key, _ids: mark_beach_posted(key, config.DB_PATH),
    )


async def process_road_alerts(chat_list: list[str]) -> None:
    """Post road alerts that still need posting."""
    await post_pending(
        get_road_alerts_needing_post(config.DB_PATH),
        chat_list,
        label="road alert",
        format_fn=format_road_alert,
        key_fn=lambda a: a["alert_key"],
        mark_fn=lambda key, _ids: mark_road_posted(key, config.DB_PATH),
    )
