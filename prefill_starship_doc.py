"""Prefill the database with the Starship documentary episodes online now.

Run once before starting the bot (``python prefill_starship_doc.py``) so that
the bot announces only episodes of SpaceX's Starship documentary series
published from now on, instead of posting the ones already out on its first
cycle. Safe to run again: episodes already known keep their posting state, and
any not yet posted are marked as posted without sending anything.

With ``--if-empty`` it does nothing when the database already has documentary
episodes. Docker Compose runs it that way before every bot start, so only the
first start prefills, and episodes released while the bot is down are still
announced.

The work is done by :func:`src.bot.orchestrator.prefill_starship_documentaries`;
this script only reports the result.
"""

from __future__ import annotations

import argparse
import sys

from src.bot.orchestrator import prefill_starship_documentaries
from src.core import config
from src.core.logging import logger
from src.data import init_db
from src.data.starship_doc_repo import starship_documentaries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--if-empty",
        action="store_true",
        help="do nothing if the database already has Starship documentary episodes",
    )
    args = parser.parse_args(argv)

    try:
        if args.if_empty:
            init_db(config.DB_PATH)
            known = starship_documentaries.count(config.DB_PATH)
            if known:
                logger.info(
                    f"Starship documentary prefill skipped: {known} episode(s) already known"
                )
                return 0
        marked = prefill_starship_documentaries()
        online = starship_documentaries.count(config.DB_PATH)
        latest = starship_documentaries.latest_episode(config.DB_PATH)
    except Exception:
        logger.exception("Starship documentary prefill failed")
        return 1
    span = f" (Ep001–Ep{latest:03d})" if online else ""
    logger.info(
        f"Starship documentary prefill done: {online} episode(s) online{span}, "
        f"{marked} marked as already posted"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
