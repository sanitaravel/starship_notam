"""Source-file watcher and in-place self-restart support.

This module lets the long-running bot process detect when its own source code
changes on disk and restart itself so the new code takes effect — without
requiring an external process manager.

Design
------
* :func:`snapshot_sources` walks every ``*.py`` file under the installed
  ``starship_notam`` package and records a fingerprint (size + modification
  time) for each. The fingerprint is deliberately cheap: it never reads file
  contents, so scanning is fast even for a large package.
* :func:`sources_changed` re-scans and compares against a previous snapshot.
  Added, removed, or modified files all count as a change.
* :func:`restart_process` replaces the current process image via
  :func:`os.execv`, re-launching the exact same command
  (``python -m starship_notam`` or ``starship-notam``) in place. The PID is
  preserved and no supervisor is required. Because ``execv`` never returns on
  success, callers should treat it as terminal.

The orchestrator checks for changes only at a *safe point* — between full
ingestion/delivery cycles — so a restart never interrupts an in-flight scrape,
render, or Telegram post.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict

from starship_notam.core.logging import logger

# Fingerprint of a single source file: (size_bytes, mtime_ns).
_FileFingerprint = tuple[int, int]

# A snapshot maps an absolute file path -> its fingerprint.
Snapshot = Dict[str, _FileFingerprint]

# Root of the installed package: this file lives at
#   starship_notam/bot/reloader.py  ->  parents[1] == starship_notam/
_PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _iter_source_files(package_root: Path):
    """Yield every ``*.py`` file under *package_root*, skipping caches."""
    for path in package_root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        yield path


def _fingerprint(path: Path) -> _FileFingerprint:
    """Return a cheap (size, mtime_ns) fingerprint for *path*."""
    st = path.stat()
    return (st.st_size, st.st_mtime_ns)


def snapshot_sources(package_root: Path | None = None) -> Snapshot:
    """Return a fingerprint snapshot of all package source files.

    Parameters
    ----------
    package_root:
        Directory to scan. Defaults to the installed ``starship_notam``
        package directory. Injectable for testing.
    """
    root = package_root or _PACKAGE_ROOT
    snapshot: Snapshot = {}
    for path in _iter_source_files(root):
        try:
            snapshot[str(path)] = _fingerprint(path)
        except OSError:
            # File vanished between listing and stat (e.g. mid-deploy). Treat
            # it as absent; a later scan will pick up the settled state.
            continue
    return snapshot


def sources_changed(previous: Snapshot, package_root: Path | None = None) -> bool:
    """Return ``True`` if any source file changed since *previous*.

    A change is any added, removed, or modified (size/mtime) ``*.py`` file.
    The first differing file is logged to aid debugging deploys.
    """
    current = snapshot_sources(package_root)

    if current == previous:
        return False

    added = current.keys() - previous.keys()
    removed = previous.keys() - current.keys()
    modified = {
        p for p in current.keys() & previous.keys() if current[p] != previous[p]
    }

    if added:
        logger.info("Code update detected: %d new file(s), e.g. %s",
                    len(added), sorted(added)[0])
    if removed:
        logger.info("Code update detected: %d removed file(s), e.g. %s",
                    len(removed), sorted(removed)[0])
    if modified:
        logger.info("Code update detected: %d modified file(s), e.g. %s",
                    len(modified), sorted(modified)[0])

    return True


def _restart_argv() -> list[str]:
    """Build the argv used to relaunch this process in place.

    ``sys.argv[0]`` is unreliable across launch styles (``python -m pkg`` sets
    it to the package's ``__main__`` path). We reconstruct a stable command:

    * If launched via ``python -m starship_notam``, relaunch the same module
      with the same interpreter.
    * Otherwise (console-script / direct script), relaunch ``sys.argv`` as-is
      under the current interpreter.
    """
    # ``__main__.__package__`` is set to the package name when launched with
    # ``python -m <package>``.
    main_module = sys.modules.get("__main__")
    launched_as_module = bool(getattr(main_module, "__package__", "") )

    if launched_as_module and getattr(main_module, "__package__", ""):
        return [sys.executable, "-m", "starship_notam", *sys.argv[1:]]

    return [sys.executable, *sys.argv]


def restart_process() -> None:
    """Replace the current process image with a fresh interpreter.

    Flushes standard streams, then calls :func:`os.execv`, which does not
    return on success. Any raised exception is logged and re-raised so callers
    can decide how to proceed (the orchestrator logs and continues running the
    old code rather than dying).
    """
    argv = _restart_argv()
    logger.info("Restarting process to load updated code: %s", " ".join(argv))

    # Ensure buffered log/output is written before the image is replaced.
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:  # pragma: no cover - flushing should not fail
        pass

    try:
        os.execv(argv[0], argv)
    except OSError:
        logger.exception("Self-restart via os.execv failed; continuing on current code")
        raise
