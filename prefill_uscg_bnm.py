"""Prefill the database with the Starship bulletins the USCG BNM feeds list now.

Run once before starting the bot (``python prefill_uscg_bnm.py``) so that the
bot announces only Broadcast Notices to Mariners issued from now on, instead
of posting the hazard areas of past Starship flights on its first cycle. Safe
to run again: bulletins already known keep their posting state, and any not
yet posted are marked as posted without sending anything.

With ``--if-empty`` it does nothing when the database already has USCG BNM
bulletins. Docker Compose runs it that way before every bot start, so only
the first start prefills, and bulletins issued while the bot is down are
still announced.

The work is done by :func:`src.bot.orchestrator.prefill_uscg_bnm_notices`;
this script only reports the result.
"""

from __future__ import annotations

import argparse
import sys

from src.bot.orchestrator import prefill_uscg_bnm_notices
from src.core import config
from src.core.logging import logger
from src.data import init_db
from src.data.uscg_bnm_repo import uscg_bnm_notices


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--if-empty",
        action="store_true",
        help="do nothing if the database already has USCG BNM bulletins",
    )
    args = parser.parse_args(argv)

    try:
        if args.if_empty:
            init_db(config.DB_PATH)
            known = uscg_bnm_notices.count(config.DB_PATH)
            if known:
                logger.info(f"USCG BNM prefill skipped: {known} bulletin(s) already known")
                return 0
        marked = prefill_uscg_bnm_notices()
    except Exception:
        logger.exception("USCG BNM prefill failed")
        return 1
    logger.info(f"USCG BNM prefill done: {marked} bulletin(s) marked as already posted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
