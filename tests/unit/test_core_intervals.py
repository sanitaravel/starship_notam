"""Per-source poll intervals are read from ``<SOURCE>_INTERVAL_MINUTES``."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.core.config import DEFAULT_SOURCE_INTERVALS, source_intervals

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_defaults():
    assert source_intervals({}) == {
        "notams": 10,
        "faa_advisories": 5,
        "fcc_els": 30,
        "faa_drs": 60,
        "compass": 30,
        "federal_register": 30,
        "regulations_gov": 30,
        "sec_edgar": 10,
        "uscg_bnm": 15,
        "starbase": 5,
    }
    assert list(source_intervals({})) == list(DEFAULT_SOURCE_INTERVALS)


def test_override():
    assert source_intervals({"FCC_ELS_INTERVAL_MINUTES": "60"})["fcc_els"] == 60


def test_empty_value_means_default():
    assert source_intervals({"SEC_EDGAR_INTERVAL_MINUTES": ""})["sec_edgar"] == 10


@pytest.mark.parametrize("value", ["0", "-5", "abc", "1.5"])
def test_bad_value_raises(value):
    with pytest.raises(RuntimeError, match="STARBASE_INTERVAL_MINUTES"):
        source_intervals({"STARBASE_INTERVAL_MINUTES": value})


def test_runs_per_hour_default_is_12(tmp_path):
    env_file = tmp_path / "empty.env"
    env_file.write_text("")
    env = {
        k: v
        for k, v in os.environ.items()
        if k != "RUNS_PER_HOUR" and not k.endswith("_INTERVAL_MINUTES")
    }
    env.update(
        NOTAM_ENV_FILE=str(env_file),
        DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/1/token",
    )
    result = subprocess.run(
        [sys.executable, "-c", "import src.core.config as c; print(c.RUNS_PER_HOUR)"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "12"
