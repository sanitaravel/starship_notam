"""SpaceX filings on SEC EDGAR (8-K, 10-Q, 10-K, offerings)."""

from __future__ import annotations

import asyncio

from src.bot.formatting import format_sec_edgar_filing
from src.bot.orchestrator.posting import post_pending
from src.core import config
from src.core.logging import logger
from src.data import (
    init_db,
    sec_edgar_filings,
)
from src.scrapers import sec_edgar_filings_fetcher


def _save_sec_edgar_filings(filings: list[dict]) -> None:
    """Persist fetched filings, oldest first.

    EDGAR lists filings newest first; saving in reverse gives new rows
    ascending ids, so several filings found in one cycle are posted in filing
    order.
    """
    for record in reversed(filings):
        try:
            sec_edgar_filings.save(record, config.DB_PATH)
        except Exception:
            logger.exception(f"Failed to save SEC EDGAR filing {record}")


async def process_sec_edgar_filings(chat_list: list[str]) -> None:
    """Fetch SpaceX's SEC EDGAR filings and post new ones."""
    if not config.SEC_USER_AGENT:
        logger.info("SEC_USER_AGENT is not set; skipping SEC EDGAR")
        return

    logger.info("Refreshing SEC EDGAR filings needing Telegram post")
    try:
        filings = await asyncio.to_thread(sec_edgar_filings_fetcher.fetch)
        _save_sec_edgar_filings(filings or [])
    except Exception:
        logger.exception("Failed to fetch and parse SEC EDGAR filings")

    await post_pending(
        sec_edgar_filings.needing_post(config.DB_PATH),
        chat_list,
        label="SEC EDGAR filing",
        format_fn=format_sec_edgar_filing,
        key_fn=lambda f: f["accession_number"],
        mark_fn=lambda key, ids: sec_edgar_filings.mark_posted(
            key, ids, config.DB_PATH
        ),
    )


def prefill_sec_edgar_filings() -> int:
    """Record every filing EDGAR lists now as already posted.

    Run once before starting the bot so it announces only filings made
    afterwards. Returns the number of filings marked; raises ``RuntimeError``
    when ``SEC_USER_AGENT`` is unset or the filings could not be fetched.
    """
    if not config.SEC_USER_AGENT:
        raise RuntimeError("SEC_USER_AGENT is not set")
    init_db(config.DB_PATH)
    filings = sec_edgar_filings_fetcher.fetch()
    if filings is None:
        raise RuntimeError("Could not fetch the SEC EDGAR filings")
    _save_sec_edgar_filings(filings)
    return sec_edgar_filings.mark_many_posted(
        [f["accession_number"] for f in filings], None, config.DB_PATH
    )
