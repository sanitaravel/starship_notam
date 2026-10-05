"""Main orchestration loop and scheduling for the Telegram NOTAM bot.

This module ties together every layer of the application: it drives the
scrapers to fetch fresh data, persists results through the ``data`` layer,
renders NOTAM images via the ``visualization`` layer, formats messages via
``bot.formatting`` and delivers them through ``bot.transport``.

It is the ONLY module permitted to import from multiple packages
(``scrapers``, ``data``, ``visualization``, ``bot.formatting``,
``bot.transport`` and ``core``).

Design constraints:
    - Every processing step is wrapped in try/except: exceptions are logged
      and the loop continues to the next step. The main loop must never
      terminate due to a transient error.
    - Scrapers return data without persisting; this module is responsible for
      persistence via the ``data`` layer.
    - Blocking work (Selenium scraping, HTTP fetches, matplotlib rendering) is
      delegated to worker threads via ``asyncio.to_thread``.

Public entry points:
    async main_loop() -> None
    async generate_and_send() -> None
"""

from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

from starship_notam.core import config
from starship_notam.core.logging import logger

from starship_notam.bot.formatting import (
    build_notam_caption,
    format_beach_alert,
    format_faa_activity,
    format_faa_license,
    format_fcc_els_application,
    format_road_alert,
)
from starship_notam.bot.transport import (
    send_message,
    send_photo,
)

from starship_notam.bot.reloader import (
    restart_process,
    snapshot_sources,
    sources_changed,
)

from starship_notam.data import (
    get_beach_alerts_needing_post,
    get_faa_activities_needing_post,
    get_faa_licenses_needing_post,
    get_fcc_els_applications_needing_post,
    get_notams_needing_images,
    get_road_alerts_needing_post,
    init_db,
    mark_beach_posted,
    mark_faa_activity_posted,
    mark_faa_license_posted,
    mark_fcc_els_application_posted,
    mark_image_generated,
    mark_road_posted,
    save_beach_alert,
    save_faa_activity,
    save_faa_license,
    save_fcc_els_application,
    save_notam,
    save_road_alert,
)

from starship_notam.parsers.coord_parser import parse_coords_from_text
from starship_notam.parsers.notam_parser import parse_notam

from starship_notam.scrapers import (
    fetch_faa_advisory,
    fetch_faa_license,
    fetch_fcc_els_applications,
    fetch_starbase_status,
    search_notams_many,
)

from starship_notam.visualization.image_composer import plot_single_notam


# Project root is two levels up from this file:
#   starship_notam/bot/orchestrator.py -> starship_notam/ -> project root
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_MAPS_DIR = _PROJECT_ROOT / "maps"


# --- Individual processing steps -------------------------------------------


# Free-text keywords searched on the FAA NOTAM site, in order.
_NOTAM_KEYWORDS = ("starship", "spacex brownsville", "re-entry")


def _keyword_patterns(keyword: str) -> list[re.Pattern]:
    """Return one whole-word pattern per word of ``keyword``.

    Hyphens are optional, so ``re-entry`` matches RE-ENTRY, REENTRY and
    RE ENTRY, but not the ENTRY in "VFR ENTRY".
    """
    patterns = []
    for term in keyword.split():
        body = re.escape(term).replace(r"\-", r"-?\s?")
        patterns.append(re.compile(rf"\b{body}\b", re.IGNORECASE))
    return patterns


def _matches_keyword(text: str, keyword: str) -> bool:
    """True when every word of ``keyword`` appears in ``text`` (any order)."""
    return all(p.search(text) for p in _keyword_patterns(keyword))


def _persist_notam_results(results: list[dict], keyword: str) -> None:
    """Parse and persist each scraped NOTAM result dict.

    The scraper returns dicts with a ``number`` field (e.g. ``A0669/26``) and
    an ``icao_message`` field containing the raw NOTAM text. We parse the text
    and derive the persisted ``name`` from ``number`` by replacing ``/`` with
    ``_`` (captions reverse this mapping).

    The FAA free-text search is fuzzy (``re-entry`` also returns unrelated
    "VFR ENTRY" notices), so a result is only saved when its message actually
    contains ``keyword``.
    """
    for result in results or []:
        try:
            icao_message = result.get("icao_message") or ""
            if not icao_message.strip():
                logger.info(
                    f"Skipping NOTAM {result.get('number', '<no-number>')}: empty ICAO message"
                )
                continue
            if not _matches_keyword(icao_message, keyword):
                logger.info(
                    f"Skipping NOTAM {result.get('number', '<no-number>')}: "
                    f"message does not contain '{keyword}'"
                )
                continue
            parsed = parse_notam(icao_message)
            raw_number = str(result.get("number") or "").strip()
            if not raw_number:
                logger.info("Skipping NOTAM with no number field")
                continue
            name = raw_number.replace("/", "_")
            save_notam(name, parsed, config.DB_PATH)
        except Exception:
            logger.exception(
                f"Failed to persist NOTAM {result.get('number', '<unknown>')}"
            )


async def _refresh_notams_from_source() -> None:
    """Scrape NOTAMs for the configured keywords and persist the results.

    All keywords run in one browser session (see ``search_notams_many``);
    a failure for one keyword does not stop the others.
    """
    try:
        logger.info(f"Running NOTAM requests for keywords: {', '.join(_NOTAM_KEYWORDS)}")
        results = await asyncio.to_thread(search_notams_many, _NOTAM_KEYWORDS)
    except Exception:
        logger.exception("NOTAM request failed: could not start the browser")
        return
    for keyword in _NOTAM_KEYWORDS:
        _persist_notam_results(results.get(keyword), keyword)


async def _process_notam_images(chat_list: list[str]) -> None:
    """Render and deliver images for NOTAMs that still need one."""
    pending = get_notams_needing_images(config.DB_PATH)
    if not pending:
        logger.info("No NOTAMs needing images at this time")
        return

    logger.info(f"Found {len(pending)} NOTAMs needing images")
    os.makedirs(_MAPS_DIR, exist_ok=True)

    for name, parsed in pending:
        try:
            e_text = parsed.get("E") or ""
            coords = parse_coords_from_text(e_text)
            if not coords:
                logger.info(
                    f"No coords parsed for {name}; skipping image generation"
                )
                # still mark as generated so it won't retry endlessly
                mark_image_generated(name, config.DB_PATH)
                continue

            outpath = str(_MAPS_DIR / f"{name}_map.png")
            try:
                # plot_single_notam is blocking (matplotlib) — run in a thread.
                # It derives the coordinates itself so multi-area NOTAMs keep
                # their separate polygons.
                await asyncio.to_thread(plot_single_notam, name, parsed, outpath)
                logger.info(f"Generated image for {name} -> {outpath}")
            except Exception:
                logger.exception(f"Failed to generate image for {name}")
                continue

            success_any = False
            caption = build_notam_caption(name, parsed)
            for chat_id in chat_list:
                try:
                    sent = await send_photo(chat_id, outpath, caption=caption)
                    if sent:
                        success_any = True
                    # small pause to reduce likelihood of rate limiting
                    await asyncio.sleep(0.2)
                except Exception:
                    logger.exception(f"Error sending image to chat {chat_id}")

            if success_any:
                logger.info(
                    f"Sent image for {name} to Telegram; marking in DB and deleting file"
                )
                try:
                    mark_image_generated(name, config.DB_PATH)
                except Exception:
                    logger.exception(
                        f"Failed to mark image_generated for {name}"
                    )
                try:
                    os.remove(outpath)
                except Exception:
                    logger.exception(f"Failed to delete image {outpath}")
            else:
                logger.error(
                    f"Failed to send image for {name} to any configured chat; keeping file for retry"
                )

        except Exception:
            logger.exception(f"Unhandled error while processing {name}")


# Pause after each Telegram send to stay clear of rate limits.
_SEND_PAUSE_SECONDS = 5


async def _post_pending(
    items: list[dict],
    chat_list: list[str],
    *,
    label: str,
    format_fn,
    key_fn,
    mark_fn,
) -> None:
    """Send each pending item to every chat and mark it posted on success.

    ``format_fn(item)`` builds the message text, ``key_fn(item)`` returns the
    item's identifier and ``mark_fn(key, message_ids)`` records the post.
    An item is marked posted only when at least one send succeeded; otherwise
    it stays pending and is retried on the next cycle.
    """
    if not items:
        logger.info(f"No {label} needing Telegram post at this time")
        return

    logger.info(f"Found {len(items)} {label} needing post to Telegram")
    for item in items:
        key = key_fn(item)
        try:
            text = format_fn(item)

            message_ids = []
            for chat_id in chat_list:
                message_id = await send_message(chat_id, text)
                if message_id:
                    logger.info(f"Sent {label} {key} to chat {chat_id}")
                    message_ids.append(message_id)
                else:
                    logger.warning(f"Failed to send {label} {key} to chat {chat_id}")
                await asyncio.sleep(_SEND_PAUSE_SECONDS)

            if not message_ids:
                logger.error(
                    f"Failed to send {label} {key} to any configured chat; "
                    "keeping unposted for retry"
                )
                continue

            logger.info(f"Marking {label} {key} as posted")
            try:
                mark_fn(key, ",".join(str(mid) for mid in message_ids))
            except Exception:
                logger.exception(f"Failed to mark {label} {key} as posted")

        except Exception:
            logger.exception(f"Failed to send {label} {key}")


async def _process_faa_activities(chat_list: list[str]) -> None:
    """Fetch FAA advisories, persist them, and post any that need posting."""
    logger.info("Refreshing FAA activities needing Telegram post")
    try:
        logger.info("Getting FAA activities")
        activities = await asyncio.to_thread(fetch_faa_advisory)
        for activity in activities or []:
            try:
                save_faa_activity(activity, config.DB_PATH)
            except Exception:
                logger.exception(f"Failed to save FAA activity {activity}")
    except Exception:
        logger.exception("Failed to fetch and parse FAA advisory")

    await _post_pending(
        get_faa_activities_needing_post(config.DB_PATH),
        chat_list,
        label="FAA activity",
        format_fn=format_faa_activity,
        key_fn=lambda a: a["mission"],
        mark_fn=lambda key, ids: mark_faa_activity_posted(key, ids, config.DB_PATH),
    )


async def _process_fcc_els_applications(chat_list: list[str]) -> None:
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

    await _post_pending(
        get_fcc_els_applications_needing_post(config.DB_PATH),
        chat_list,
        label="FCC ELS application",
        format_fn=format_fcc_els_application,
        key_fn=lambda a: a["file_number"],
        mark_fn=lambda key, ids: mark_fcc_els_application_posted(key, ids, config.DB_PATH),
    )


async def _process_faa_licenses(chat_list: list[str]) -> None:
    """Fetch the FAA DRS launch license, persist it, and post any changes.

    The (blocking, Selenium-backed) fetch is offloaded to a worker thread; the
    record is persisted through the data layer (which performs SHA-256 change
    detection and re-flags changed records for posting).
    """
    logger.info("Refreshing FAA DRS launch license needing Telegram post")
    try:
        logger.info("Getting FAA DRS launch license")
        record = await asyncio.to_thread(fetch_faa_license)
        if record:
            try:
                save_faa_license(record, config.DB_PATH)
            except Exception:
                logger.exception(f"Failed to save FAA DRS license {record}")
    except Exception:
        logger.exception("Failed to fetch and parse FAA DRS launch license")

    await _post_pending(
        get_faa_licenses_needing_post(config.DB_PATH),
        chat_list,
        label="FAA DRS license",
        format_fn=format_faa_license,
        key_fn=lambda lic: lic["doc_unique_id"],
        mark_fn=lambda key, ids: mark_faa_license_posted(key, ids, config.DB_PATH),
    )


async def _ingest_starbase_alerts() -> None:
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


async def _process_beach_alerts(chat_list: list[str]) -> None:
    """Post beach alerts that still need posting."""
    await _post_pending(
        get_beach_alerts_needing_post(config.DB_PATH),
        chat_list,
        label="beach alert",
        format_fn=format_beach_alert,
        key_fn=lambda a: a["alert_key"],
        mark_fn=lambda key, _ids: mark_beach_posted(key, config.DB_PATH),
    )


async def _process_road_alerts(chat_list: list[str]) -> None:
    """Post road alerts that still need posting."""
    await _post_pending(
        get_road_alerts_needing_post(config.DB_PATH),
        chat_list,
        label="road alert",
        format_fn=format_road_alert,
        key_fn=lambda a: a["alert_key"],
        mark_fn=lambda key, _ids: mark_road_posted(key, config.DB_PATH),
    )


# --- Orchestration ----------------------------------------------------------


async def generate_and_send() -> None:
    """Run one full ingestion + delivery cycle.

    Each step is independently wrapped in try/except (inside the helper
    functions), so a failure in one step does not prevent the others from
    running. All content is delivered to the single configured Telegram
    channel (``config.TELEGRAM_CHANNEL_ID``).
    """
    await _refresh_notams_from_source()
    chat_list = [config.TELEGRAM_CHANNEL_ID]
    await _process_notam_images(chat_list)
    await _process_faa_activities(chat_list)
    await _process_fcc_els_applications(chat_list)
    await _process_faa_licenses(chat_list)
    await _ingest_starbase_alerts()
    await _process_beach_alerts(chat_list)
    await _process_road_alerts(chat_list)


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


async def sleep_until_next_run() -> None:
    """Sleep until the next scheduled run slot based on ``RUNS_PER_HOUR``."""
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

    await asyncio.sleep(sleep_seconds)


async def main_loop() -> None:
    """Start the bot: initialize and loop forever.

    The loop wraps ``generate_and_send`` in try/except so a transient failure
    never terminates monitoring. ``asyncio.CancelledError`` is handled to log a
    clean stop.
    """
    ensure_setup()
    logger.info("Starting Telegram NOTAM bot loop (python-telegram-bot)")

    # Snapshot our own source files so we can detect code updates on disk
    # and restart in place to pick them up (see bot.reloader).
    source_snapshot = snapshot_sources()

    try:
        while True:
            try:
                await generate_and_send()
            except Exception:
                logger.exception("Error in generate_and_send")

            await sleep_until_next_run()

            # Safe point between cycles: if our source changed on disk,
            # restart in place so the new code takes effect. restart_process
            # replaces the process image and does not return on success; if
            # it fails it logs and we keep running the current code.
            if sources_changed(source_snapshot):
                logger.info("Source change detected at safe point; restarting")
                try:
                    restart_process()
                except Exception:
                    logger.exception("Restart failed; refreshing snapshot and continuing")
                    source_snapshot = snapshot_sources()

    except asyncio.CancelledError:
        logger.info("Telegram NOTAM bot stopped")


if __name__ == "__main__":
    asyncio.run(main_loop())
