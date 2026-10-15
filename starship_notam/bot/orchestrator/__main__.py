"""Run the bot loop: ``python -m starship_notam.bot.orchestrator``."""

import asyncio

from starship_notam.bot.orchestrator.loop import main_loop

asyncio.run(main_loop())
