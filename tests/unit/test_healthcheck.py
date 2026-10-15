"""The container healthcheck passes only while heartbeats are recent."""

from __future__ import annotations

import os
import subprocess
import sys
import time

from starship_notam import healthcheck

RUNS_PER_HOUR = 2  # every 30 minutes -> healthy up to 45 minutes


def test_fresh_heartbeat_is_healthy(tmp_path):
    path = tmp_path / "beat"
    healthcheck.write_heartbeat(path)

    assert healthcheck.is_healthy(path, runs_per_hour=RUNS_PER_HOUR)


def test_heartbeat_within_interval_plus_grace_is_healthy(tmp_path):
    path = tmp_path / "beat"
    path.write_text("1000\n")

    assert healthcheck.is_healthy(
        path, runs_per_hour=RUNS_PER_HOUR, now=1000 + 45 * 60
    )


def test_stale_heartbeat_is_unhealthy(tmp_path):
    path = tmp_path / "beat"
    path.write_text("1000\n")

    assert not healthcheck.is_healthy(
        path, runs_per_hour=RUNS_PER_HOUR, now=1000 + 45 * 60 + 1
    )


def test_missing_heartbeat_is_unhealthy(tmp_path):
    assert not healthcheck.is_healthy(
        tmp_path / "missing", runs_per_hour=RUNS_PER_HOUR
    )


def test_garbled_heartbeat_is_unhealthy(tmp_path):
    path = tmp_path / "beat"
    path.write_text("not a time")

    assert not healthcheck.is_healthy(path, runs_per_hour=RUNS_PER_HOUR)


def run_check(path, env_extra=None):
    env = {"NOTAM_HEARTBEAT_FILE": str(path), **(env_extra or {})}
    return subprocess.run(
        [sys.executable, "-m", "starship_notam.healthcheck"],
        env={**_base_env(), **env},
        capture_output=True,
        text=True,
    )


def _base_env():
    # No TELEGRAM_BOT_TOKEN on purpose: the check must not load the config.
    return {
        key: value
        for key, value in os.environ.items()
        if key not in ("TELEGRAM_BOT_TOKEN", "NOTAM_ENV_FILE")
    }


def test_module_exits_zero_on_fresh_heartbeat(tmp_path):
    path = tmp_path / "beat"
    path.write_text(f"{time.time():.0f}\n")

    assert run_check(path).returncode == 0


def test_module_exits_one_without_heartbeat(tmp_path):
    result = run_check(tmp_path / "missing")

    assert result.returncode == 1
    assert "No recent heartbeat" in result.stderr


def test_module_reads_runs_per_hour(tmp_path):
    # 40 minutes old: healthy at 2 runs/hour (45 min), stale at 4 (30 min).
    path = tmp_path / "beat"
    path.write_text(f"{time.time() - 40 * 60:.0f}\n")

    assert run_check(path, {"RUNS_PER_HOUR": "2"}).returncode == 0
    assert run_check(path, {"RUNS_PER_HOUR": "4"}).returncode == 1
