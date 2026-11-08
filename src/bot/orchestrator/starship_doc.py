"""Episodes of SpaceX's Starship documentary series."""

from __future__ import annotations

import asyncio

from src.bot.formatting import format_starship_documentary
from src.bot.orchestrator.posting import post_pending
from src.core import config
from src.core.logging import logger
from src.data import (
    init_db,
    starship_documentaries,
)
from src.scrapers import starship_documentary_fetcher


def _save_starship_documentaries(episodes: list[dict]) -> None:
    """Persist fetched episodes in ascending episode order.

    The fetcher returns them in that order already; sorting keeps the row ids,
    and so the posting order, right regardless.
    """
    for record in sorted(episodes, key=lambda e: e["episode"]):
        try:
            starship_documentaries.save(record, config.DB_PATH)
        except Exception:
            logger.exception(f"Failed to save Starship documentary episode {record}")


async def process_starship_documentaries(chat_list: list[str]) -> None:
    """Look for new documentary episodes and post them."""
    logger.info("Refreshing Starship documentary episodes needing a post")
    try:
        # Stored-but-unposted episodes count too: they are already pending.
        latest = starship_documentaries.latest_episode(config.DB_PATH)
        episodes = await asyncio.to_thread(starship_documentary_fetcher.fetch_after, latest)
        _save_starship_documentaries(episodes or [])
    except Exception:
        logger.exception("Failed to fetch Starship documentary episodes")

    await post_pending(
        starship_documentaries.needing_post(config.DB_PATH),
        chat_list,
        label="Starship documentary episode",
        format_fn=format_starship_documentary,
        key_fn=lambda e: e["episode_id"],
        mark_fn=lambda key, ids: starship_documentaries.mark_posted(
            key, ids, config.DB_PATH
        ),
    )


def prefill_starship_documentaries() -> int:
    """Record every episode that is online now as already posted.

    Run once before starting the bot so it announces only later episodes.
    Returns the number of episodes marked; raises ``RuntimeError`` when the
    episodes could not be fetched.
    """
    init_db(config.DB_PATH)
    episodes = starship_documentary_fetcher.fetch_after(0)
    if episodes is None:
        raise RuntimeError("Could not fetch the Starship documentary episodes")
    _save_starship_documentaries(episodes)
    return starship_documentaries.mark_many_posted(
        [e["episode_id"] for e in episodes], None, config.DB_PATH
    )
