"""FAA Federal Register documents about SpaceX."""

from __future__ import annotations

import asyncio

from starship_notam.bot.formatting import format_federal_register_document
from starship_notam.bot.orchestrator.posting import post_pending
from starship_notam.core import config
from starship_notam.core.logging import logger
from starship_notam.data import (
    get_federal_register_documents_needing_post,
    init_db,
    mark_federal_register_document_posted,
    mark_federal_register_documents_posted,
    save_federal_register_document,
)
from starship_notam.scrapers import fetch_federal_register_documents


def _save_federal_register_documents(documents: list[dict]) -> None:
    """Persist fetched Federal Register documents, oldest first.

    The API lists documents newest first; saving in reverse gives new rows
    ascending ids, so several documents found in one cycle are posted in
    publication order.
    """
    for record in reversed(documents):
        try:
            save_federal_register_document(record, config.DB_PATH)
        except Exception:
            logger.exception(f"Failed to save Federal Register document {record}")


async def process_federal_register_documents(chat_list: list[str]) -> None:
    """Fetch FAA Federal Register documents about SpaceX and post new ones."""
    logger.info("Refreshing Federal Register documents needing Telegram post")
    try:
        documents = await asyncio.to_thread(fetch_federal_register_documents)
        _save_federal_register_documents(documents or [])
    except Exception:
        logger.exception("Failed to fetch and parse Federal Register documents")

    await post_pending(
        get_federal_register_documents_needing_post(config.DB_PATH),
        chat_list,
        label="Federal Register document",
        format_fn=format_federal_register_document,
        key_fn=lambda d: d["document_number"],
        mark_fn=lambda key, ids: mark_federal_register_document_posted(
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
    documents = fetch_federal_register_documents()
    if documents is None:
        raise RuntimeError("Could not fetch the Federal Register documents")
    _save_federal_register_documents(documents)
    return mark_federal_register_documents_posted(
        [d["document_number"] for d in documents], None, config.DB_PATH
    )
