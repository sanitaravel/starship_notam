"""The main loop: run every step once per cycle, then sleep until the next slot."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from functools import partial

from src.bot.orchestrator import shutdown
from src.bot.orchestrator.compass import process_compass_files
from src.bot.orchestrator.faa import process_faa_activities, process_faa_licenses
from src.bot.orchestrator.fcc_els import process_fcc_els_applications
from src.bot.orchestrator.federal_register import (
    process_federal_register_documents,
)
from src.bot.orchestrator.notams import (
    process_notam_images,
    refresh_notams_from_source,
)
from src.bot.orchestrator.regulations_gov import (
    process_regulations_gov_documents,
)
from src.bot.orchestrator.sec_edgar import process_sec_edgar_filings
from src.bot.orchestrator.starbase import (
    ingest_starbase_alerts,
    process_beach_alerts,
    process_road_alerts,
)
from src.core import config
from src.core.logging import logger
from src.data import init_db
from src.healthcheck import write_heartbeat


async def generate_and_send() -> None:
    """Run one full ingestion + delivery cycle.

    Each step is independently wrapped in try/except (inside the step
    functions), so a failure in one step does not prevent the others from
    running. All content is delivered to the single configured Telegram
    channel (``config.TELEGRAM_CHANNEL_ID``). After a stop request the cycle
    ends early, between items (see ``shutdown``).
    """
    chat_list = [config.TELEGRAM_CHANNEL_ID]
    steps = (
        refresh_notams_from_source,
        partial(process_notam_images, chat_list),
        partial(process_faa_activities, chat_list),
        partial(process_fcc_els_applications, chat_list),
        partial(process_faa_licenses, chat_list),
        partial(process_compass_files, chat_list),
        partial(process_federal_register_documents, chat_list),
        # After the Federal Register step, so a notice it just stored is not
        # announced a second time (see regulations_gov).
        partial(process_regulations_gov_documents, chat_list),
        partial(process_sec_edgar_filings, chat_list),
        ingest_starbase_alerts,
        partial(process_beach_alerts, chat_list),
        partial(process_road_alerts, chat_list),
    )
    for step in steps:
        if shutdown.stopping():
            logger.info("Stop requested; skipping the rest of this cycle")
            return
        await step()
        # After every step, not just every cycle: the first cycle on a new
        # database posts everything and can run longer than a deploy waits
        # for the bot to turn healthy.
        _record_heartbeat()


def ensure_setup() -> None:
    """Validate required configuration and initialize the database.

    ``core.config`` already raises at import time if ``TELEGRAM_BOT_TOKEN`` is
    missing, but we keep an explicit guard here for defensive clarity and
    ensure the database schema exists before the loop starts.
    """
    if not config.TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN must be set in environment")
        raise SystemExit(1)
    # ensure DB exists/initialized
    init_db(config.DB_PATH)


async def sleep_until_next_run(stop: asyncio.Event) -> None:
    """Sleep until the next scheduled run slot based on ``RUNS_PER_HOUR``.

    Returns early as soon as *stop* is set.
    """
    interval_minutes = 60 / config.RUNS_PER_HOUR

    now = datetime.now()

    minutes_since_hour = now.minute + now.second / 60

    next_slot = (int(minutes_since_hour // interval_minutes) + 1) * interval_minutes

    next_run = now.replace(minute=0, second=0, microsecond=0)

    if next_slot >= 60:
        next_run += timedelta(hours=1)
    else:
        next_run += timedelta(minutes=next_slot)

    sleep_seconds = (next_run - now).total_seconds()

    logger.info(
        f"Next run scheduled for {next_run:%Y-%m-%d %H:%M:%S} "
        f"(sleeping {sleep_seconds:.0f}s)"
    )

    try:
        await asyncio.wait_for(stop.wait(), timeout=sleep_seconds)
    except TimeoutError:
        pass


def _record_heartbeat() -> None:
    """Write the heartbeat the container healthcheck reads."""
    try:
        write_heartbeat()
    except OSError:
        logger.warning("Could not write the heartbeat file", exc_info=True)


async def main_loop() -> None:
    """Start the bot: initialize and loop until asked to stop.

    The loop wraps ``generate_and_send`` in try/except so a transient failure
    never terminates monitoring. After each cycle it writes the heartbeat for
    the healthcheck. SIGTERM or SIGINT stops the loop after the current item
    (see ``shutdown.install_stop_handlers``); ``asyncio.CancelledError`` is
    handled to log a clean stop.
    """
    ensure_setup()
    logger.info(f"Starting Starship NOTAM bot {config.VERSION}")

    stop = shutdown.new_stop_event()
    remove_stop_handlers = shutdown.install_stop_handlers(stop)

    try:
        while not stop.is_set():
            try:
                await generate_and_send()
            except Exception:
                logger.exception("Error in generate_and_send")

            _record_heartbeat()

            if not stop.is_set():
                await sleep_until_next_run(stop)

    except asyncio.CancelledError:
        pass
    finally:
        remove_stop_handlers()
        shutdown.clear_stop_event()

    logger.info("Telegram NOTAM bot stopped")
