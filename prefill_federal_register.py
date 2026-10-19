"""Prefill the database with the documents the Federal Register search returns now.

Run once before starting the bot (``python prefill_federal_register.py``) so
that the bot announces only FAA Federal Register documents about SpaceX
published from now on, instead of posting the newest page of the back
catalogue on its first cycle. Safe to run again: documents already known keep
their posting state, and any not yet posted are marked as posted without
sending anything.

With ``--if-empty`` it does nothing when the database already has Federal
Register documents. Docker Compose runs it that way before every bot start,
so only the first start prefills, and documents published while the bot is
down are still announced.

The work is done by
:func:`src.bot.orchestrator.prefill_federal_register_documents`;
this script only reports the result.
"""

from __future__ import annotations

import argparse
import sys

from src.bot.orchestrator import prefill_federal_register_documents
from src.core import config
from src.core.logging import logger
from src.data import init_db
from src.data.federal_register_repo import federal_register_documents


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--if-empty",
        action="store_true",
        help="do nothing if the database already has Federal Register documents",
    )
    args = parser.parse_args(argv)

    try:
        if args.if_empty:
            init_db(config.DB_PATH)
            known = federal_register_documents.count(config.DB_PATH)
            if known:
                logger.info(
                    f"Federal Register prefill skipped: {known} document(s) already known"
                )
                return 0
        marked = prefill_federal_register_documents()
    except Exception:
        logger.exception("Federal Register prefill failed")
        return 1
    logger.info(
        f"Federal Register prefill done: {marked} document(s) marked as already posted"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
