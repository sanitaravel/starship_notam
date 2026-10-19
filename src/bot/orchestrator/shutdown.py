"""Stop requests shared by the main loop and the processing steps."""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Callable

from src.core.logging import logger


# Set by main_loop on SIGTERM or SIGINT. The steps check it between items, so
# a stop never separates a send from its "posted" mark, yet does not wait for
# the rest of the cycle either: what is left stays pending for the next start.
_stop: asyncio.Event | None = None


def stopping() -> bool:
    """True once a stop was requested."""
    return _stop is not None and _stop.is_set()


def new_stop_event() -> asyncio.Event:
    """Create the stop event the steps check and return it."""
    global _stop
    _stop = asyncio.Event()
    return _stop


def clear_stop_event() -> None:
    """Forget the stop event once the loop has exited."""
    global _stop
    _stop = None


def install_stop_handlers(stop: asyncio.Event) -> Callable[[], None]:
    """Set *stop* on SIGTERM or SIGINT; return a function that removes the handlers.

    ``docker stop`` and a deploy send SIGTERM. The cycle in progress then
    ends after the item it is on, so no item is sent without being marked
    posted. A second signal cancels the loop at once. Event loops on Windows do not support
    signal handlers; there Ctrl-C still raises ``KeyboardInterrupt``.
    """
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()

    def on_signal(sig: signal.Signals) -> None:
        if stop.is_set():
            logger.warning(f"Received {sig.name} again; stopping immediately")
            task.cancel()
            return
        logger.info(f"Received {sig.name}; stopping after the current item")
        stop.set()

    installed = []
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, on_signal, sig)
        except (NotImplementedError, RuntimeError):
            continue
        installed.append(sig)

    def remove() -> None:
        for sig in installed:
            loop.remove_signal_handler(sig)

    return remove
