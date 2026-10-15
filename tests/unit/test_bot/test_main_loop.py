"""The bot stops between items, never between a send and its "posted" mark.

A deploy or ``docker stop`` sends SIGTERM. ``_post_pending`` sends a message
first and marks it posted afterwards, so a kill in between posts the same item
twice on the next start. After a stop request the item in progress finishes,
the rest of the cycle is skipped, and the loop exits.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys

import pytest

from starship_notam.bot import orchestrator

POSIX_ONLY = pytest.mark.skipif(
    sys.platform == "win32", reason="event loop signal handlers are POSIX-only"
)


@pytest.fixture
def loop_harness(monkeypatch):
    """Stub set-up and the heartbeat; record cycle steps and heartbeats."""
    events: list[str] = []
    monkeypatch.setattr(orchestrator, "ensure_setup", lambda: None)
    monkeypatch.setattr(
        orchestrator, "write_heartbeat", lambda: events.append("heartbeat")
    )

    def set_cycle(cycle):
        monkeypatch.setattr(orchestrator, "generate_and_send", cycle)

    return set_cycle, events


def capture_stop_event(monkeypatch) -> dict:
    """Replace the signal handlers; expose the loop's stop event instead."""
    captured: dict = {}

    def install(stop):
        captured["stop"] = stop
        return lambda: None

    monkeypatch.setattr(orchestrator, "_install_stop_handlers", install)
    return captured


async def test_stop_during_cycle_lets_the_running_step_finish(monkeypatch, loop_harness):
    set_cycle, events = loop_harness
    captured = capture_stop_event(monkeypatch)

    async def cycle():
        events.append("start")
        captured["stop"].set()
        await asyncio.sleep(0)
        events.append("end")

    async def must_not_sleep(stop):
        raise AssertionError("loop slept after a stop request")

    set_cycle(cycle)
    monkeypatch.setattr(orchestrator, "sleep_until_next_run", must_not_sleep)

    await asyncio.wait_for(orchestrator.main_loop(), timeout=5)

    assert events == ["start", "end", "heartbeat"]


async def test_stop_during_sleep_exits_without_waiting(monkeypatch, loop_harness):
    set_cycle, events = loop_harness
    captured = capture_stop_event(monkeypatch)

    async def cycle():
        events.append("cycle")
        asyncio.get_running_loop().call_later(0.05, captured["stop"].set)

    set_cycle(cycle)

    # The real sleep lasts until the next :00/:30 slot unless stopped.
    await asyncio.wait_for(orchestrator.main_loop(), timeout=5)

    assert events == ["cycle", "heartbeat"]


async def test_failed_cycle_still_writes_heartbeat(monkeypatch, loop_harness):
    set_cycle, events = loop_harness
    captured = capture_stop_event(monkeypatch)

    async def cycle():
        captured["stop"].set()
        raise RuntimeError("source down")

    set_cycle(cycle)

    await asyncio.wait_for(orchestrator.main_loop(), timeout=5)

    assert events == ["heartbeat"]


async def test_heartbeat_write_error_does_not_stop_the_loop(monkeypatch, loop_harness):
    set_cycle, events = loop_harness
    captured = capture_stop_event(monkeypatch)
    cycles = []

    def broken_heartbeat():
        raise OSError("read-only file system")

    async def cycle():
        cycles.append(1)
        if len(cycles) == 2:
            captured["stop"].set()

    async def no_sleep(stop):
        pass

    set_cycle(cycle)
    monkeypatch.setattr(orchestrator, "write_heartbeat", broken_heartbeat)
    monkeypatch.setattr(orchestrator, "sleep_until_next_run", no_sleep)

    await asyncio.wait_for(orchestrator.main_loop(), timeout=5)

    assert len(cycles) == 2


async def test_stop_while_posting_finishes_the_item_and_skips_the_rest(monkeypatch):
    stop = asyncio.Event()
    monkeypatch.setattr(orchestrator, "_stop", stop)
    monkeypatch.setattr(orchestrator, "_SEND_PAUSE_SECONDS", 0)
    sent, marked = [], []

    async def send(chat_id, text):
        sent.append(text)
        stop.set()
        return 42

    monkeypatch.setattr(orchestrator, "send_message", send)

    await orchestrator._post_pending(
        [{"id": "a"}, {"id": "b"}],
        ["chat"],
        label="items",
        format_fn=lambda item: item["id"],
        key_fn=lambda item: item["id"],
        mark_fn=lambda key, ids: marked.append(key),
    )

    assert sent == ["a"]
    assert marked == ["a"]


async def test_stop_skips_the_remaining_steps(monkeypatch):
    stop = asyncio.Event()
    monkeypatch.setattr(orchestrator, "_stop", stop)
    ran = []

    async def refresh():
        ran.append("refresh")
        stop.set()

    async def later_step(*args):
        ran.append("later")

    monkeypatch.setattr(orchestrator, "_refresh_notams_from_source", refresh)
    for name in (
        "_process_notam_images",
        "_process_faa_activities",
        "_process_fcc_els_applications",
        "_process_faa_licenses",
        "_process_compass_files",
        "_process_federal_register_documents",
        "_ingest_starbase_alerts",
        "_process_beach_alerts",
        "_process_road_alerts",
    ):
        monkeypatch.setattr(orchestrator, name, later_step)

    await orchestrator.generate_and_send()

    assert ran == ["refresh"]


async def test_heartbeat_after_every_step(monkeypatch):
    events = []
    monkeypatch.setattr(orchestrator, "write_heartbeat", lambda: events.append("heartbeat"))

    async def step(*args):
        events.append("step")

    for name in (
        "_refresh_notams_from_source",
        "_process_notam_images",
        "_process_faa_activities",
        "_process_fcc_els_applications",
        "_process_faa_licenses",
        "_process_compass_files",
        "_process_federal_register_documents",
        "_ingest_starbase_alerts",
        "_process_beach_alerts",
        "_process_road_alerts",
    ):
        monkeypatch.setattr(orchestrator, name, step)

    await orchestrator.generate_and_send()

    assert events == ["step", "heartbeat"] * 10


async def test_stop_flag_is_cleared_after_the_loop(monkeypatch, loop_harness):
    set_cycle, _ = loop_harness
    captured = capture_stop_event(monkeypatch)

    async def cycle():
        captured["stop"].set()

    set_cycle(cycle)

    await orchestrator.main_loop()

    assert orchestrator._stop is None
    assert not orchestrator._stopping()


@POSIX_ONLY
async def test_sigterm_finishes_cycle_then_exits(loop_harness):
    set_cycle, events = loop_harness

    async def cycle():
        events.append("start")
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.sleep(0.05)
        events.append("end")

    set_cycle(cycle)

    await asyncio.wait_for(asyncio.create_task(orchestrator.main_loop()), timeout=5)

    assert events == ["start", "end", "heartbeat"]


@POSIX_ONLY
async def test_second_signal_stops_immediately(loop_harness):
    set_cycle, events = loop_harness

    async def cycle():
        events.append("start")
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.sleep(0.05)
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.sleep(10)
        events.append("end")

    set_cycle(cycle)

    await asyncio.wait_for(asyncio.create_task(orchestrator.main_loop()), timeout=5)

    assert events == ["start"]


@POSIX_ONLY
async def test_signal_handlers_are_removed_on_exit(loop_harness):
    set_cycle, _ = loop_harness

    async def cycle():
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.sleep(0.05)

    set_cycle(cycle)

    await asyncio.create_task(orchestrator.main_loop())

    assert not asyncio.get_running_loop().remove_signal_handler(signal.SIGTERM)
