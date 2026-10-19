"""Prefill the database with the SpaceX filings SEC EDGAR lists now.

Run once before starting the bot (``python prefill_sec_edgar.py``) so that the
bot announces only SpaceX filings (8-K, 10-Q, 10-K, offerings) made from now
on, instead of posting the whole post-IPO back catalogue on its first cycle.
Safe to run again: filings already known keep their posting state, and any
not yet posted are marked as posted without sending anything.

With ``--if-empty`` it does nothing when the database already has SEC EDGAR
filings. Docker Compose runs it that way before every bot start, so only the
first start prefills, and filings made while the bot is down are still
announced.

Without ``SEC_USER_AGENT`` the source is disabled, so there is nothing to
prefill: the script says so and succeeds. Once it is set, the next start
(with an empty table) prefills.

The work is done by :func:`src.bot.orchestrator.prefill_sec_edgar_filings`;
this script only reports the result.
"""

from __future__ import annotations

import argparse
import sys

from src.bot.orchestrator import prefill_sec_edgar_filings
from src.core import config
from src.core.logging import logger
from src.data import init_db
from src.data.sec_edgar_repo import sec_edgar_filings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--if-empty",
        action="store_true",
        help="do nothing if the database already has SEC EDGAR filings",
    )
    args = parser.parse_args(argv)

    if not config.SEC_USER_AGENT:
        logger.info("SEC EDGAR prefill skipped: SEC_USER_AGENT is not set")
        return 0

    try:
        if args.if_empty:
            init_db(config.DB_PATH)
            known = sec_edgar_filings.count(config.DB_PATH)
            if known:
                logger.info(f"SEC EDGAR prefill skipped: {known} filing(s) already known")
                return 0
        marked = prefill_sec_edgar_filings()
    except Exception:
        logger.exception("SEC EDGAR prefill failed")
        return 1
    logger.info(f"SEC EDGAR prefill done: {marked} filing(s) marked as already posted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
