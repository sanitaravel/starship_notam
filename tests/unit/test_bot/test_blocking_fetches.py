"""Blocking HTTP fetches run in worker threads, not on the event loop.

Regression test for fix-plan step 13: ``fetch_faa_advisory`` and
``fetch_starbase_status`` (``requests.get`` with a 30s timeout) were called
directly from async code, freezing the event loop while they ran.
"""

from __future__ import annotations

import threading

from starship_notam.bot import orchestrator


async def test_faa_advisory_fetch_runs_off_the_event_loop(monkeypatch):
    loop_thread = threading.get_ident()
    seen = []

    def fetch():
        seen.append(threading.get_ident())
        return []

    monkeypatch.setattr(orchestrator, "fetch_faa_advisory", fetch)
    monkeypatch.setattr(orchestrator, "get_faa_activities_needing_post", lambda db: [])

    await orchestrator._process_faa_activities(["chat"])

    assert seen and seen[0] != loop_thread


async def test_starbase_fetch_runs_off_the_event_loop(monkeypatch):
    loop_thread = threading.get_ident()
    seen = []

    def fetch():
        seen.append(threading.get_ident())
        return {"beach": None, "road_delays": []}

    monkeypatch.setattr(orchestrator, "fetch_starbase_status", fetch)

    await orchestrator._ingest_starbase_alerts()

    assert seen and seen[0] != loop_thread
