"""Main orchestration loop and scheduling for the Telegram NOTAM bot.

This package ties together every layer of the application: it drives the
scrapers to fetch fresh data, persists results through the ``data`` layer,
renders NOTAM images via the ``visualization`` layer, formats messages via
``bot.formatting`` and delivers them through ``bot.transport``.

It is the ONLY package permitted to import from multiple packages
(``scrapers``, ``data``, ``visualization``, ``bot.formatting``,
``bot.transport`` and ``core``).

Design constraints:
    - Every processing step is wrapped in try/except: exceptions are logged
      and the loop continues to the next step. The main loop must never
      terminate due to a transient error.
    - Scrapers return data without persisting; this package is responsible for
      persistence via the ``data`` layer.
    - Blocking work (Selenium scraping, HTTP fetches, matplotlib rendering) is
      delegated to worker threads via ``asyncio.to_thread``.

Submodules:
    loop              main_loop, generate_and_send, scheduling, set-up
    shutdown          stop requests (SIGTERM/SIGINT) shared by the steps
    posting           post_pending: send an item, then mark it posted
    notams            scrape NOTAMs, render and send their images
    faa               FAA planned activities and launch licenses
    fcc_els           FCC ELS applications
    compass           COMPASS Master Slide Deck files (+ prefill)
    federal_register  Federal Register documents (+ prefill)
    starbase          Starbase beach and road alerts

Public entry points:
    async main_loop() -> None
    async generate_and_send() -> None
    prefill_compass_files() -> int
    prefill_federal_register_documents() -> int
"""

from src.bot.orchestrator.compass import prefill_compass_files
from src.bot.orchestrator.federal_register import (
    prefill_federal_register_documents,
)
from src.bot.orchestrator.loop import (
    ensure_setup,
    generate_and_send,
    main_loop,
    sleep_until_next_run,
)

__all__ = [
    "ensure_setup",
    "generate_and_send",
    "main_loop",
    "prefill_compass_files",
    "prefill_federal_register_documents",
    "sleep_until_next_run",
]
