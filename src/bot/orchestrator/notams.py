"""Scrape NOTAMs, then render and send an image for each new one."""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

from src.bot.formatting import build_notam_caption
from src.bot.orchestrator import shutdown
from src.bot.transport import send_photo
from src.core import config
from src.core.logging import logger
from src.data import get_notams_needing_images, mark_image_generated, save_notam
from src.parsers.coord_parser import parse_coords_from_text
from src.parsers.notam_parser import parse_notam
from src.scrapers import search_notams_many
from src.visualization.image_composer import plot_single_notam


# Project root is three levels up from this file:
#   src/bot/orchestrator/notams.py -> src/ -> project root
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_MAPS_DIR = _PROJECT_ROOT / "maps"

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


def matches_keyword(text: str, keyword: str) -> bool:
    """True when every word of ``keyword`` appears in ``text`` (any order)."""
    return all(p.search(text) for p in _keyword_patterns(keyword))


def persist_notam_results(results: list[dict], keyword: str) -> None:
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
            if not matches_keyword(icao_message, keyword):
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


async def refresh_notams_from_source() -> None:
    """Scrape NOTAMs for the configured keywords and persist the results.

    All keywords run on one HTTP session (see ``search_notams_many``);
    a failure for one keyword does not stop the others.
    """
    try:
        logger.info(f"Running NOTAM requests for keywords: {', '.join(_NOTAM_KEYWORDS)}")
        results = await asyncio.to_thread(search_notams_many, _NOTAM_KEYWORDS)
    except Exception:
        logger.exception("NOTAM request failed")
        return
    for keyword in _NOTAM_KEYWORDS:
        persist_notam_results(results.get(keyword), keyword)


async def process_notam_images(chat_list: list[str]) -> None:
    """Render and deliver images for NOTAMs that still need one."""
    pending = get_notams_needing_images(config.DB_PATH)
    if not pending:
        logger.info("No NOTAMs needing images at this time")
        return

    logger.info(f"Found {len(pending)} NOTAMs needing images")
    os.makedirs(_MAPS_DIR, exist_ok=True)

    for name, parsed in pending:
        if shutdown.stopping():
            logger.info("Stop requested; leaving the remaining NOTAM images for the next start")
            return
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
                    f"Sent image for {name}; marking in DB and deleting file"
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
