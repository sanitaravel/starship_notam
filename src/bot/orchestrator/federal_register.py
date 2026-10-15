"""FAA Federal Register documents about SpaceX."""

from __future__ import annotations

import asyncio

from src.bot.formatting import format_federal_register_document
from src.bot.orchestrator.posting import post_pending
from src.core import config
from src.core.logging import logger
from src.data import (
    federal_register_documents,
    init_db,
)
from src.scrapers import federal_register_documents_fetcher


def _save_federal_register_documents(documents: list[dict]) -> None:
    """Persist fetched Federal Register documents, oldest first.

    The API lists documents newest first; saving in reverse gives new rows
    ascending ids, so several documents found in one cycle are posted in
    publication order.
    """
    for record in reversed(documents):
        try:
            federal_register_documents.save(record, config.DB_PATH)
        except Exception:
            logger.exception(f"Failed to save Federal Register document {record}")


async def process_federal_register_documents(chat_list: list[str]) -> None:
    """Fetch FAA Federal Register documents about SpaceX and post new ones."""
    logger.info("Refreshing Federal Register documents needing Telegram post")
    try:
        documents = await asyncio.to_thread(federal_register_documents_fetcher.fetch)
        _save_federal_register_documents(documents or [])
    except Exception:
        logger.exception("Failed to fetch and parse Federal Register documents")

    await post_pending(
        federal_register_documents.needing_post(config.DB_PATH),
        chat_list,
        label="Federal Register document",
        format_fn=format_federal_register_document,
        key_fn=lambda d: d["document_number"],
        mark_fn=lambda key, ids: federal_register_documents.mark_posted(
            key, ids, config.DB_PATH
        ),
    )


def prefill_federal_register_documents() -> int:
    """Record every document the Federal Register search returns as already posted.

    Run once before starting the bot so it announces only documents published
    afterwards. Returns the number of documents marked; raises
    ``RuntimeError`` when the search could not be fetched.
    """
    init_db(config.DB_PATH)
    documents = federal_register_documents_fetcher.fetch()
    if documents is None:
        raise RuntimeError("Could not fetch the Federal Register documents")
    _save_federal_register_documents(documents)
    return federal_register_documents.mark_many_posted(
        [d["document_number"] for d in documents], None, config.DB_PATH
    )
