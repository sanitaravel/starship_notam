"""Prefill the database with the documents the Regulations.gov searches return now.

Run once before starting the bot (``python prefill_regulations_gov.py``) so
that the bot announces only FAA/USCG Regulations.gov documents about Starship
posted from now on, instead of posting the newest page of the back catalogue
on its first cycle. Safe to run again: documents already known keep their
posting state, and any not yet posted are marked as posted without sending
anything.

With ``--if-empty`` it does nothing when the database already has
Regulations.gov documents. Docker Compose runs it that way before every bot
start, so only the first start prefills, and documents posted while the bot
is down are still announced.

Without ``REGULATIONS_GOV_API_KEY`` the source is disabled, so there is
nothing to prefill: the script says so and succeeds. Once a key is added, the
next start (with an empty table) prefills.

The work is done by
:func:`src.bot.orchestrator.prefill_regulations_gov_documents`;
this script only reports the result.
"""

from __future__ import annotations

import argparse
import sys

from src.bot.orchestrator import prefill_regulations_gov_documents
from src.core import config
from src.core.logging import logger
from src.data import init_db
from src.data.regulations_gov_repo import regulations_gov_documents


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--if-empty",
        action="store_true",
        help="do nothing if the database already has Regulations.gov documents",
    )
    args = parser.parse_args(argv)

    if not config.REGULATIONS_GOV_API_KEY:
        logger.info("Regulations.gov prefill skipped: REGULATIONS_GOV_API_KEY is not set")
        return 0

    try:
        if args.if_empty:
            init_db(config.DB_PATH)
            known = regulations_gov_documents.count(config.DB_PATH)
            if known:
                logger.info(
                    f"Regulations.gov prefill skipped: {known} document(s) already known"
                )
                return 0
        marked = prefill_regulations_gov_documents()
    except Exception:
        logger.exception("Regulations.gov prefill failed")
        return 1
    logger.info(
        f"Regulations.gov prefill done: {marked} document(s) marked as already posted"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
