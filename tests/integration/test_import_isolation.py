"""Import-isolation integration tests.

These tests verify the runtime import behaviour promised by the modularization
design (see requirements 9.1, 9.2, 9.3, 9.5, 9.6):

    * A single layer can be imported on its own, quickly, and without dragging
      in the heavy optional dependencies belonging to *other* layers
      (Selenium, python-telegram-bot, Cartopy, Matplotlib).
    * Importing the parser / data / visualization layers has no observable
      side effects: no database file is created, no database connection is
      opened, and no network request is issued.
    * Optional heavy dependencies are only imported when a function that needs
      them is actually called — never at module-import time (lazy imports).

To keep the checks free of contamination from modules that a previous test may
already have imported into the shared interpreter, each isolation assertion is
run in a *fresh* Python subprocess. The subprocess reports back the modules it
observed in ``sys.modules`` and the wall-clock import time, and the test asserts
against that report.

Requirements: 9.1, 9.2, 9.3, 9.5, 9.6
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# Project root = two levels up from this file (tests/integration/ -> project).
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Heavy optional dependencies. Importing a layer module must NOT pull these into
# ``sys.modules`` as a side effect; they are only allowed to load lazily inside
# the function bodies that actually need them.
HEAVY_MODULES = ["selenium", "telegram", "cartopy", "matplotlib"]

# Maximum time (seconds) any single layer is allowed to take to import.
# Requirements 9.2, 9.3, 9.6 mandate a 2-second ceiling.
IMPORT_TIME_LIMIT_S = 2.0


def _run_import_probe(module_name: str, watch_modules: list[str]) -> dict:
    """Import ``module_name`` in a fresh subprocess and report observations.

    Returns a dict with keys:
        ``import_seconds`` : float wall-clock time spent on the import
        ``loaded``         : list[str] of ``watch_modules`` present in
                             ``sys.modules`` after the import
        ``created_files``  : list[str] of *.db files created under the project
                             root during the import
    Raises AssertionError with the subprocess stderr if the import failed.
    """
    watch_repr = repr(watch_modules)
    script = textwrap.dedent(
        f"""
        import json, sys, time, glob, os

        project_root = {str(PROJECT_ROOT)!r}
        watch = {watch_repr}

        # Snapshot of *.db files before the import so we can detect any that the
        # import created as a side effect.
        before = set(glob.glob(os.path.join(project_root, "**", "*.db"), recursive=True))

        start = time.perf_counter()
        __import__({module_name!r})
        elapsed = time.perf_counter() - start

        after = set(glob.glob(os.path.join(project_root, "**", "*.db"), recursive=True))

        result = {{
            "import_seconds": elapsed,
            "loaded": [m for m in watch if m in sys.modules],
            "created_files": sorted(after - before),
        }}
        print("PROBE_RESULT:" + json.dumps(result))
        """
    )

    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"Importing {module_name!r} in an isolated subprocess failed "
        f"(exit code {proc.returncode}).\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )

    marker = "PROBE_RESULT:"
    line = next(
        (ln for ln in proc.stdout.splitlines() if ln.startswith(marker)),
        None,
    )
    assert line is not None, (
        f"Probe for {module_name!r} produced no result line.\n"
        f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    import json

    return json.loads(line[len(marker):])


# ---------------------------------------------------------------------------
# 9.1 — Parser layer imports without DB / Selenium / Telegram side effects
# ---------------------------------------------------------------------------
def test_parsers_import_without_heavy_dependencies():
    """Importing the parser layer must not load Selenium/Telegram/Cartopy/Matplotlib.

    Requirement 9.1: the parser modules import without a database connection or
    network request, and without dragging in the heavy I/O dependencies that
    belong to other layers.
    """
    result = _run_import_probe("starship_notam.parsers", HEAVY_MODULES)

    assert result["loaded"] == [], (
        "Importing starship_notam.parsers pulled in heavy dependencies that "
        f"should be lazy: {result['loaded']}"
    )


def test_parsers_import_creates_no_database_file():
    """Importing the parser layer must not create a database file on disk.

    Requirement 9.1: no database file exists / is created and no connection is
    established as a side effect of importing the parser layer.
    """
    result = _run_import_probe("starship_notam.parsers", HEAVY_MODULES)

    assert result["created_files"] == [], (
        "Importing starship_notam.parsers created database file(s) as a side "
        f"effect: {result['created_files']}"
    )


def test_parsers_do_not_import_requests_or_sqlite():
    """Parser modules must not load ``requests`` or open ``sqlite3`` at import.

    Requirement 9.1 (no network as a side effect) and the parser layer's
    dependency boundary: the parser layer must not perform network I/O nor
    touch the database at import time. ``sqlite3`` is a stdlib module so it may
    legitimately be present via unrelated imports; here we only assert that
    ``requests`` (the network client) is not loaded by importing parsers.
    """
    result = _run_import_probe("starship_notam.parsers", ["requests"] + HEAVY_MODULES)

    assert "requests" not in result["loaded"], (
        "Importing starship_notam.parsers loaded the 'requests' HTTP client, "
        "implying a network dependency leaked into the parser layer."
    )


# ---------------------------------------------------------------------------
# 9.2 — Data layer imports quickly without Selenium/Telegram/Cartopy
# ---------------------------------------------------------------------------
def test_data_layer_imports_without_heavy_dependencies():
    """Requirement 9.2: the data layer imports without Selenium/Telegram/Cartopy."""
    result = _run_import_probe("starship_notam.data", HEAVY_MODULES)

    assert result["loaded"] == [], (
        "Importing starship_notam.data pulled in heavy dependencies that "
        f"belong to other layers: {result['loaded']}"
    )


def test_data_layer_imports_within_time_limit():
    """Requirement 9.2: the data layer imports within the 2-second ceiling."""
    result = _run_import_probe("starship_notam.data", HEAVY_MODULES)

    assert result["import_seconds"] < IMPORT_TIME_LIMIT_S, (
        f"Importing starship_notam.data took {result['import_seconds']:.3f}s, "
        f"exceeding the {IMPORT_TIME_LIMIT_S}s limit."
    )


# ---------------------------------------------------------------------------
# 9.3 — Visualization layer imports quickly without a running bot / network
# ---------------------------------------------------------------------------
def test_visualization_layer_imports_without_bot_or_network_deps():
    """Requirement 9.3: importing the visualization layer needs no running bot.

    Neither the Telegram transport (python-telegram-bot) nor the HTTP client
    should be loaded merely by importing the visualization layer, and the heavy
    Cartopy/Matplotlib plotting stack must stay lazy.
    """
    result = _run_import_probe(
        "starship_notam.visualization", ["telegram", "requests"] + HEAVY_MODULES
    )

    assert result["loaded"] == [], (
        "Importing starship_notam.visualization pulled in dependencies that "
        f"should be lazy or belong to other layers: {result['loaded']}"
    )


def test_visualization_layer_imports_within_time_limit():
    """Requirement 9.3: the visualization layer imports within 2 seconds."""
    result = _run_import_probe("starship_notam.visualization", HEAVY_MODULES)

    assert result["import_seconds"] < IMPORT_TIME_LIMIT_S, (
        f"Importing starship_notam.visualization took "
        f"{result['import_seconds']:.3f}s, exceeding the {IMPORT_TIME_LIMIT_S}s limit."
    )


# ---------------------------------------------------------------------------
# 9.6 — Every single layer imports quickly without ImportError
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "layer",
    [
        "starship_notam.core",
        "starship_notam.parsers",
        "starship_notam.data",
        "starship_notam.scrapers",
        "starship_notam.bot",
        "starship_notam.visualization",
    ],
)
def test_each_layer_imports_within_time_limit(layer):
    """Requirement 9.6: any single layer imports within 2s without ImportError.

    ``_run_import_probe`` already asserts a zero exit code, so a failed import
    (ImportError / ModuleNotFoundError) surfaces as a test failure. Here we
    additionally enforce the 2-second import ceiling for every layer.
    """
    result = _run_import_probe(layer, HEAVY_MODULES)

    assert result["import_seconds"] < IMPORT_TIME_LIMIT_S, (
        f"Importing {layer} took {result['import_seconds']:.3f}s, exceeding the "
        f"{IMPORT_TIME_LIMIT_S}s limit."
    )


# ---------------------------------------------------------------------------
# 9.5 — Optional dependencies are imported lazily (inside functions), and the
#        error surfaces only when the dependent function is called.
# ---------------------------------------------------------------------------
def test_scraper_selenium_import_is_lazy():
    """Requirement 9.5: Selenium is not imported when the scraper module loads.

    ``search_notams`` imports Selenium inside its body. Importing the scraper
    module (or the whole scrapers package) must therefore not load Selenium.
    """
    result = _run_import_probe("starship_notam.scrapers.notam_scraper", ["selenium"])

    assert "selenium" not in result["loaded"], (
        "Importing the notam_scraper module eagerly loaded 'selenium'; the "
        "dependency must be imported lazily inside search_notams()."
    )


def test_bot_transport_telegram_import_is_lazy():
    """Requirement 9.5: python-telegram-bot is not imported when transport loads.

    The Telegram transport imports ``telegram`` lazily inside its send
    functions, so importing the transport module must not load it.
    """
    result = _run_import_probe("starship_notam.bot.transport", ["telegram"])

    assert "telegram" not in result["loaded"], (
        "Importing the bot.transport module eagerly loaded 'telegram'; the "
        "dependency must be imported lazily inside the send functions."
    )


def test_visualization_matplotlib_and_cartopy_imports_are_lazy():
    """Requirement 9.5: Matplotlib/Cartopy load only inside render_map().

    Importing the map_renderer module must not eagerly load the heavy plotting
    stack.
    """
    result = _run_import_probe(
        "starship_notam.visualization.map_renderer", ["matplotlib", "cartopy"]
    )

    assert result["loaded"] == [], (
        "Importing map_renderer eagerly loaded the heavy plotting stack "
        f"{result['loaded']}; matplotlib/cartopy must be imported lazily inside "
        "render_map()."
    )
