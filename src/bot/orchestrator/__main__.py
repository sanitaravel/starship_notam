"""Run the bot loop: ``python -m src.bot.orchestrator``."""

import asyncio

from src.bot.orchestrator.loop import main_loop

asyncio.run(main_loop())
