"""The test suite must never write to the bot's real log file.

Regression test: tests used to log into ``logs/notam.log`` in the project
root, filling it and rotating the bot's real logs out of the 5-file window.
"""

from __future__ import annotations

import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from starship_notam.core.logging import LOG_DIR, logger

PROJECT_LOGS = Path(__file__).resolve().parents[2] / "logs"


def test_tests_log_to_a_temporary_directory():
    assert Path(LOG_DIR) == Path(os.environ["NOTAM_LOG_DIR"])
    assert Path(LOG_DIR).resolve() != PROJECT_LOGS.resolve()


def test_file_handler_points_outside_project_logs():
    files = [
        Path(h.baseFilename).resolve()
        for h in logger.handlers
        if isinstance(h, RotatingFileHandler)
    ]
    assert files, "expected a file handler"
    assert all(PROJECT_LOGS.resolve() not in f.parents for f in files)
