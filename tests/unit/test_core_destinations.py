"""The bot needs at least one destination: Telegram, Discord, or both.

``core.config`` validates them at import time, so each case imports it in a
fresh interpreter with an empty env file (the real ``.env`` must not leak in).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.bot.discord_webhook import DiscordWebhook
from src.bot.orchestrator import loop

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEBHOOK_URL = "https://discord.com/api/webhooks/1/token"
_DESTINATION_VARS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHANNEL_ID", "DISCORD_WEBHOOK_URL")


def import_config(tmp_path, **env_vars) -> subprocess.CompletedProcess:
    env_file = tmp_path / "empty.env"
    env_file.write_text("")
    env = {k: v for k, v in os.environ.items() if k not in _DESTINATION_VARS}
    env.update(NOTAM_ENV_FILE=str(env_file), **env_vars)
    return subprocess.run(
        [sys.executable, "-c", "import src.core.config"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    "env_vars",
    [
        {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHANNEL_ID": "@c"},
        {"DISCORD_WEBHOOK_URL": WEBHOOK_URL},
        {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHANNEL_ID": "@c", "DISCORD_WEBHOOK_URL": WEBHOOK_URL},
    ],
    ids=["telegram", "discord", "both"],
)
def test_valid_destinations_load(tmp_path, env_vars):
    result = import_config(tmp_path, **env_vars)

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "env_vars, message",
    [
        ({}, "No destination configured"),
        ({"TELEGRAM_BOT_TOKEN": "t", "DISCORD_WEBHOOK_URL": WEBHOOK_URL}, "must be set together"),
        ({"TELEGRAM_CHANNEL_ID": "@c"}, "must be set together"),
        ({"DISCORD_WEBHOOK_URL": "https://example.org/hook"}, "must be a Discord webhook URL"),
    ],
    ids=["none", "token-without-channel", "channel-without-token", "bad-webhook"],
)
def test_invalid_destinations_refuse_to_load(tmp_path, env_vars, message):
    result = import_config(tmp_path, **env_vars)

    assert result.returncode != 0
    assert message in result.stderr


@pytest.mark.parametrize(
    "channel, webhook, expected",
    [
        ("@c", "", ["@c"]),
        ("", WEBHOOK_URL, [DiscordWebhook(WEBHOOK_URL)]),
        ("@c", WEBHOOK_URL, ["@c", DiscordWebhook(WEBHOOK_URL)]),
    ],
    ids=["telegram", "discord", "both"],
)
def test_loop_posts_to_every_configured_destination(monkeypatch, channel, webhook, expected):
    monkeypatch.setattr(loop.config, "TELEGRAM_CHANNEL_ID", channel)
    monkeypatch.setattr(loop.config, "DISCORD_WEBHOOK_URL", webhook)

    assert loop.destinations() == expected
