"""Per-source scheduling: decide which steps run in the current cycle.

The loop wakes every ``tick_minutes``; each source has its own interval in
minutes. A source is due when it has never run, or when at least its interval
has passed since it last ran. The comparison allows half a tick of tolerance:
cycles never start exactly one tick apart (steps take time, sleeping is
imprecise), so a 30-minute source seen 29 minutes 57 seconds after its last
run must still run now rather than wait a whole extra tick.

Public API: ``StepScheduler``.
"""

from __future__ import annotations

import time
from collections.abc import Callable


class StepScheduler:
    """Tracks when each named step last ran and tells whether it is due."""

    def __init__(
        self, tick_minutes: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._tick_minutes = tick_minutes
        self._clock = clock
        self._last_run: dict[str, float] = {}

    def due(self, name: str, interval_minutes: int) -> bool:
        """Return True if ``name`` never ran or its interval has elapsed."""
        last = self._last_run.get(name)
        if last is None:
            return True
        threshold = (interval_minutes - self._tick_minutes / 2) * 60
        return self._clock() - last >= threshold

    def mark_ran(self, name: str) -> None:
        """Record that ``name`` ran just now."""
        self._last_run[name] = self._clock()
