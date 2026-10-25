"""COMPASS "Master Slide Deck" files."""

from __future__ import annotations

import asyncio

from src.bot.formatting import format_compass_file
from src.bot.orchestrator.posting import post_pending
from src.core import config
from src.core.logging import logger
from src.data import (
    compass_files,
    init_db,
)
from src.scrapers import compass_files_fetcher


def _save_compass_files(files: list[dict]) -> None:
    """Persist fetched COMPASS files, oldest first.

    The site lists files newest first; saving in reverse gives new rows
    ascending ids, so several files found in one cycle are posted in upload
    order.
    """
    for record in reversed(files):
        try:
            compass_files.save(record, config.DB_PATH)
        except Exception:
            logger.exception(f"Failed to save COMPASS file {record}")


async def process_compass_files(chat_list: list[str]) -> None:
    """Fetch the COMPASS Master Slide Deck list and post any new files."""
    logger.info("Refreshing COMPASS files needing a post")
    try:
        files = await asyncio.to_thread(compass_files_fetcher.fetch)
        _save_compass_files(files or [])
    except Exception:
        logger.exception("Failed to fetch and parse COMPASS file list")

    await post_pending(
        compass_files.needing_post(config.DB_PATH),
        chat_list,
        label="COMPASS file",
        format_fn=format_compass_file,
        key_fn=lambda f: f["file_uuid"],
        mark_fn=lambda key, ids: compass_files.mark_posted(key, ids, config.DB_PATH),
    )


def prefill_compass_files() -> int:
    """Record every file currently on the COMPASS list as already posted.

    Run once before starting the bot so it announces only files uploaded
    afterwards. Returns the number of files marked; raises ``RuntimeError``
    when the list could not be fetched.
    """
    init_db(config.DB_PATH)
    files = compass_files_fetcher.fetch()
    if files is None:
        raise RuntimeError("Could not fetch the COMPASS file list")
    _save_compass_files(files)
    return compass_files.mark_many_posted(
        [f["file_uuid"] for f in files], None, config.DB_PATH
    )
