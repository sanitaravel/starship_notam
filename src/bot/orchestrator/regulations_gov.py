"""FAA/USCG Regulations.gov documents about Starship."""

from __future__ import annotations

import asyncio

from src.bot.formatting import format_regulations_gov_document
from src.bot.orchestrator.posting import post_pending
from src.core import config
from src.core.logging import logger
from src.data import (
    federal_register_documents,
    init_db,
    regulations_gov_documents,
)
from src.scrapers import RegulationsGovFiles, fetch_regulations_gov_documents


def _save_regulations_gov_documents(documents: list[dict]) -> None:
    """Persist fetched documents (already oldest first, so ids ascend)."""
    for record in documents:
        try:
            regulations_gov_documents.save(record, config.DB_PATH)
        except Exception:
            logger.exception(f"Failed to save Regulations.gov document {record}")


def _skip_federal_register_duplicates(pending: list[dict]) -> list[dict]:
    """Mark documents the Federal Register source already knows as posted.

    Every Federal Register notice is also posted on Regulations.gov with the
    same number (``frDocNum`` == FR ``document_number``); announcing it twice
    adds nothing. Returns the documents still to be posted.
    """
    known = federal_register_documents.known(
        [d["fr_doc_num"] for d in pending if d.get("fr_doc_num")], config.DB_PATH
    )
    duplicates = [d["document_id"] for d in pending if d.get("fr_doc_num") in known]
    if duplicates:
        logger.info(
            f"Not posting {len(duplicates)} Regulations.gov document(s) already "
            f"known from the Federal Register: {', '.join(duplicates)}"
        )
        regulations_gov_documents.mark_many_posted(duplicates, None, config.DB_PATH)
    return [d for d in pending if d["document_id"] not in duplicates]


async def _attach_files(pending: list[dict]) -> list[dict]:
    """Add each document's downloadable files as ``files``.

    Returns the documents whose files could be listed; the others stay
    unposted and are tried again next cycle, so a post never goes out without
    the PDFs because of a transient API error.
    """
    ready = []
    for document in pending:
        files = await asyncio.to_thread(RegulationsGovFiles(document["document_id"]).fetch)
        if files is None:
            logger.warning(
                f"Could not list the files of Regulations.gov document "
                f"{document['document_id']}; retrying next cycle"
            )
            continue
        document["files"] = files
        ready.append(document)
    return ready


async def process_regulations_gov_documents(chat_list: list[str]) -> None:
    """Fetch FAA/USCG Regulations.gov documents about Starship and post new ones."""
    if not config.REGULATIONS_GOV_API_KEY:
        logger.info("REGULATIONS_GOV_API_KEY is not set; skipping Regulations.gov")
        return

    logger.info("Refreshing Regulations.gov documents needing a post")
    try:
        documents = await asyncio.to_thread(fetch_regulations_gov_documents)
        _save_regulations_gov_documents(documents or [])
    except Exception:
        logger.exception("Failed to fetch and parse Regulations.gov documents")

    try:
        pending = _skip_federal_register_duplicates(
            regulations_gov_documents.needing_post(config.DB_PATH)
        )
        pending = await _attach_files(pending)
    except Exception:
        logger.exception("Failed to prepare Regulations.gov documents for posting")
        return

    await post_pending(
        pending,
        chat_list,
        label="Regulations.gov document",
        format_fn=format_regulations_gov_document,
        key_fn=lambda d: d["document_id"],
        mark_fn=lambda key, ids: regulations_gov_documents.mark_posted(
            key, ids, config.DB_PATH
        ),
    )


def prefill_regulations_gov_documents() -> int:
    """Record every document the Regulations.gov searches return as already posted.

    Run once before starting the bot so it announces only documents posted
    afterwards. Returns the number of documents marked; raises
    ``RuntimeError`` when the key is unset or a search could not be fetched.
    """
    if not config.REGULATIONS_GOV_API_KEY:
        raise RuntimeError("REGULATIONS_GOV_API_KEY is not set")
    init_db(config.DB_PATH)
    documents = fetch_regulations_gov_documents()
    if documents is None:
        raise RuntimeError("Could not fetch the Regulations.gov documents")
    _save_regulations_gov_documents(documents)
    return regulations_gov_documents.mark_many_posted(
        [d["document_id"] for d in documents], None, config.DB_PATH
    )
