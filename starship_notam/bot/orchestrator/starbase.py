"""Starbase beach-closure and road-delay alerts."""

from __future__ import annotations

import asyncio

from starship_notam.bot.formatting import format_beach_alert, format_road_alert
from starship_notam.bot.orchestrator.posting import post_pending
from starship_notam.core import config
from starship_notam.core.logging import logger
from starship_notam.data import beach_alerts, road_alerts
from starship_notam.scrapers import starbase_status_fetcher


async def ingest_starbase_alerts() -> None:
    """Fetch Starbase status and persist beach/road alerts."""
    logger.info("Refreshing Starbase alerts needing Telegram post")
    try:
        logger.info("Fetching Starbase status")
        data = await asyncio.to_thread(starbase_status_fetcher.fetch)
        # ingest into DB
        if data.get("beach"):
            beach_alerts.save(data["beach"], config.DB_PATH)
        for r in data.get("road_delays", []):
            road_alerts.save(r, config.DB_PATH)
    except Exception:
        logger.exception("Failed to fetch and parse Starbase alerts")


async def process_beach_alerts(chat_list: list[str]) -> None:
    """Post beach alerts that still need posting."""
    await post_pending(
        beach_alerts.needing_post(config.DB_PATH),
        chat_list,
        label="beach alert",
        format_fn=format_beach_alert,
        key_fn=lambda a: a["alert_key"],
        mark_fn=lambda key, ids: beach_alerts.mark_posted(key, ids, config.DB_PATH),
    )


async def process_road_alerts(chat_list: list[str]) -> None:
    """Post road alerts that still need posting."""
    await post_pending(
        road_alerts.needing_post(config.DB_PATH),
        chat_list,
        label="road alert",
        format_fn=format_road_alert,
        key_fn=lambda a: a["alert_key"],
        mark_fn=lambda key, ids: road_alerts.mark_posted(key, ids, config.DB_PATH),
    )
