"""Prefill the database with the files currently on the COMPASS slide list.

Run once before starting the bot (``python prefill_compass.py``) so that the
bot announces only COMPASS "Master Slide Deck" files uploaded from now on,
instead of posting the whole existing list on its first cycle. Safe to run
again: files already known keep their posting state, and any not yet posted
are marked as posted without sending anything.

With ``--if-empty`` it does nothing when the database already has COMPASS
files. Docker Compose runs it that way before every bot start, so only the
first start prefills, and files that appear while the bot is down are still
announced.

The work is done by
:func:`src.bot.orchestrator.prefill_compass_files`; this script
only reports the result.
"""

from __future__ import annotations

import argparse
import sys

from src.bot.orchestrator import prefill_compass_files
from src.core import config
from src.core.logging import logger
from src.data import init_db
from src.data.compass_repo import compass_files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--if-empty",
        action="store_true",
        help="do nothing if the database already has COMPASS files",
    )
    args = parser.parse_args(argv)

    try:
        if args.if_empty:
            init_db(config.DB_PATH)
            known = compass_files.count(config.DB_PATH)
            if known:
                logger.info(f"COMPASS prefill skipped: {known} file(s) already known")
                return 0
        marked = prefill_compass_files()
    except Exception:
        logger.exception("COMPASS prefill failed")
        return 1
    logger.info(f"COMPASS prefill done: {marked} file(s) marked as already posted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
