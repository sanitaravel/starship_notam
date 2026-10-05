"""Prefill the database with the files currently on the COMPASS slide list.

Run once before starting the bot (``python prefill_compass.py``) so that the
bot announces only COMPASS "Master Slide Deck" files uploaded from now on,
instead of posting the whole existing list on its first cycle. Safe to run
again: files already known keep their posting state, and any not yet posted
are marked as posted without sending anything.

The work is done by
:func:`starship_notam.bot.orchestrator.prefill_compass_files`; this script
only reports the result.
"""

from __future__ import annotations

import sys

from starship_notam.bot.orchestrator import prefill_compass_files
from starship_notam.core.logging import logger


def main() -> int:
    try:
        marked = prefill_compass_files()
    except Exception:
        logger.exception("COMPASS prefill failed")
        return 1
    logger.info(f"COMPASS prefill done: {marked} file(s) marked as already posted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
