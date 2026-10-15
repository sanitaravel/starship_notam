"""Heartbeat and container healthcheck for the bot loop.

The orchestrator calls :func:`write_heartbeat` after every step of a cycle
and after every cycle. Docker runs ``python -m src.healthcheck``,
which exits 0 while the last heartbeat is recent and 1 otherwise, so a bot
that crashed at start-up or whose loop hangs shows up as ``unhealthy``. The
deploy script uses that status to accept or roll back a new version.

Standard library only and no package imports: the check runs every minute and
must not load the configuration, truncate the log file or touch the database.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

HEARTBEAT_FILE = Path(
    os.environ.get("NOTAM_HEARTBEAT_FILE")
    or Path(tempfile.gettempdir()) / "notam-heartbeat"
)

# Slack on top of the run interval: a cycle takes one to three minutes, longer
# when a source is slow.
GRACE_SECONDS = 15 * 60


def write_heartbeat(path: Path = HEARTBEAT_FILE) -> None:
    """Record that a cycle just finished."""
    path.write_text(f"{time.time():.0f}\n", encoding="ascii")


def max_age_seconds(runs_per_hour: int) -> float:
    """Oldest heartbeat that still counts as healthy."""
    return 3600 / runs_per_hour + GRACE_SECONDS


def is_healthy(
    path: Path = HEARTBEAT_FILE,
    *,
    runs_per_hour: int,
    now: float | None = None,
) -> bool:
    """Return ``True`` if the heartbeat at *path* is recent enough."""
    try:
        beat = float(path.read_text(encoding="ascii"))
    except (OSError, ValueError):
        return False
    if now is None:
        now = time.time()
    return now - beat <= max_age_seconds(runs_per_hour)


def main() -> int:
    # Same variable and default as core.config.RUNS_PER_HOUR, read directly so
    # the check does not import the configuration.
    runs_per_hour = int(os.environ.get("RUNS_PER_HOUR", "2"))
    if is_healthy(runs_per_hour=runs_per_hour):
        return 0
    print(f"No recent heartbeat in {HEARTBEAT_FILE}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
