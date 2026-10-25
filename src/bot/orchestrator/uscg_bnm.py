"""USCG Broadcast Notices to Mariners: Starship maritime hazard areas."""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

from src.bot.formatting import format_uscg_bnm_notice
from src.bot.orchestrator.posting import post_pending
from src.core import config
from src.core.logging import logger
from src.data import (
    init_db,
    uscg_bnm_notices,
)
from src.scrapers import uscg_bnm_fetchers
from src.visualization.image_composer import plot_bnm_notice


# Project root is three levels up from this file (see notams.py).
_MAPS_DIR = Path(__file__).resolve().parents[3] / "maps"


def _fetch_notices() -> tuple[list[dict], int]:
    """Fetch every topic feed; return the bulletins oldest first and the failure count.

    The Heartland and Southeast feeds each list their own bulletins newest
    first; merged and sorted by publication time, new rows get ascending ids
    and are posted in the order the Coast Guard issued them (a safety notice
    before its cancellation).
    """
    notices: dict[str, dict] = {}
    failed = 0
    for fetcher in uscg_bnm_fetchers:
        result = fetcher.fetch()
        if result is None:
            failed += 1
            continue
        for notice in result:
            notices.setdefault(notice["notice_key"], notice)
    ordered = sorted(notices.values(), key=lambda n: n.get("published_at") or "")
    return ordered, failed


def _is_relevant(notice: dict) -> bool:
    """Starship bulletins, and cancellations of a Starship bulletin already kept.

    Southeast cancellations name the flight (``STARSHIP FLIGHT 14, SUCCESSFUL
    LAUNCH``), but a bare ``CANCEL CGD-H BNM 0108-26`` does not, so it is kept
    when the safety notice it cancels is stored.
    """
    if notice.get("starship"):
        return True
    cancels = notice.get("cancels")
    return bool(cancels) and bool(
        uscg_bnm_notices.known([f"SAFETY {cancels}"], config.DB_PATH)
    )


def _save_uscg_bnm_notices(notices: list[dict]) -> list[str]:
    """Persist the Starship bulletins among *notices* (oldest first); return their keys."""
    kept = []
    for record in notices:
        try:
            if not _is_relevant(record):
                continue
            uscg_bnm_notices.save(record, config.DB_PATH)
            kept.append(record["notice_key"])
        except Exception:
            logger.exception(f"Failed to save USCG BNM {record.get('notice_key')}")
    return kept


def _render_map(notice: dict) -> str | None:
    """Draw the hazard-area card of a safety notice; None for text-only posts.

    Cancellations have no areas. A rendering failure also falls back to text,
    so the notice is still announced.
    """
    if notice.get("cancels") or not notice.get("areas"):
        return None
    os.makedirs(_MAPS_DIR, exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9-]+", "_", notice["notice_key"])
    try:
        return plot_bnm_notice(notice, str(_MAPS_DIR / f"bnm_{name}.png"))
    except Exception:
        logger.exception(f"Failed to render the map of USCG BNM {notice['notice_key']}")
        return None


async def process_uscg_bnm_notices(chat_list: list[str]) -> None:
    """Fetch the USCG BNM feeds and post new Starship bulletins."""
    logger.info("Refreshing USCG Broadcast Notices to Mariners needing a post")
    try:
        notices, _ = await asyncio.to_thread(_fetch_notices)
        _save_uscg_bnm_notices(notices)
    except Exception:
        logger.exception("Failed to fetch and parse USCG BNM feeds")

    await post_pending(
        uscg_bnm_notices.needing_post(config.DB_PATH),
        chat_list,
        label="USCG BNM",
        format_fn=format_uscg_bnm_notice,
        key_fn=lambda n: n["notice_key"],
        mark_fn=lambda key, ids: uscg_bnm_notices.mark_posted(key, ids, config.DB_PATH),
        photo_fn=_render_map,
    )


def prefill_uscg_bnm_notices() -> int:
    """Record every Starship bulletin the feeds list now as already posted.

    Run once before starting the bot so it announces only bulletins issued
    afterwards. Returns the number of bulletins marked; raises
    ``RuntimeError`` when any feed could not be fetched (a missing feed would
    have its back catalogue posted on the first cycle).
    """
    init_db(config.DB_PATH)
    notices, failed = _fetch_notices()
    if failed:
        raise RuntimeError(f"Could not fetch {failed} USCG BNM feed(s)")
    kept = _save_uscg_bnm_notices(notices)
    return uscg_bnm_notices.mark_many_posted(kept, None, config.DB_PATH)
