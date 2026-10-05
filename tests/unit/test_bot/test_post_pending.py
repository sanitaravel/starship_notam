"""Pending items are marked posted only when a Telegram send succeeded.

Regression test for fix-plan step 6: FAA activities, beach alerts and road
alerts used to be marked posted even when every send failed, so they were
silently lost. All five post types now share ``_post_pending``.
"""

from __future__ import annotations

import pytest

from starship_notam.bot import orchestrator

# processor, "needing post" getter, mark function, item, expected mark args
CASES = [
    (
        "_process_faa_activities",
        "get_faa_activities_needing_post",
        "mark_faa_activity_posted",
        {"mission": "Starship Flight 15"},
        ("Starship Flight 15", "42"),
    ),
    (
        "_process_fcc_els_applications",
        "get_fcc_els_applications_needing_post",
        "mark_fcc_els_application_posted",
        {"file_number": "0123-EX-ST-2026"},
        ("0123-EX-ST-2026", "42"),
    ),
    (
        "_process_faa_licenses",
        "get_faa_licenses_needing_post",
        "mark_faa_license_posted",
        {"doc_unique_id": "DRSDOCID1"},
        ("DRSDOCID1", "42"),
    ),
    (
        "_process_beach_alerts",
        "get_beach_alerts_needing_post",
        "mark_beach_posted",
        {"alert_key": "beach-key"},
        ("beach-key",),
    ),
    (
        "_process_road_alerts",
        "get_road_alerts_needing_post",
        "mark_road_posted",
        {"alert_key": "road-key"},
        ("road-key",),
    ),
]
IDS = [case[0] for case in CASES]


@pytest.fixture
def harness(monkeypatch):
    """Stub out scraping, formatting, sleeping and the DB; record marks."""
    marks: list[tuple] = []

    async def no_sleep(_seconds):
        pass

    monkeypatch.setattr(orchestrator.asyncio, "sleep", no_sleep)
    for fetcher in ("fetch_faa_advisory", "fetch_fcc_els_applications"):
        monkeypatch.setattr(orchestrator, fetcher, lambda: [])
    monkeypatch.setattr(orchestrator, "fetch_faa_license", lambda: None)
    for fmt in (
        "format_faa_activity",
        "format_fcc_els_application",
        "format_faa_license",
        "format_beach_alert",
        "format_road_alert",
    ):
        monkeypatch.setattr(orchestrator, fmt, lambda item: "text")

    def setup(getter, mark_fn, item, message_id):
        monkeypatch.setattr(orchestrator, getter, lambda db_path: [item])
        monkeypatch.setattr(
            orchestrator, mark_fn, lambda *args: marks.append(args[:-1])
        )

        async def fake_send(chat_id, text):
            return message_id

        monkeypatch.setattr(orchestrator, "send_message", fake_send)

    return setup, marks


@pytest.mark.parametrize("processor, getter, mark_fn, item, expected", CASES, ids=IDS)
async def test_failed_send_leaves_item_unposted(
    harness, processor, getter, mark_fn, item, expected
):
    setup, marks = harness
    setup(getter, mark_fn, item, message_id=None)

    await getattr(orchestrator, processor)(["chat"])

    assert marks == []


@pytest.mark.parametrize("processor, getter, mark_fn, item, expected", CASES, ids=IDS)
async def test_successful_send_marks_item_posted(
    harness, processor, getter, mark_fn, item, expected
):
    setup, marks = harness
    setup(getter, mark_fn, item, message_id=42)

    await getattr(orchestrator, processor)(["chat"])

    assert marks == [expected]


async def test_message_ids_from_several_chats_are_joined(harness):
    setup, marks = harness
    setup(
        "get_fcc_els_applications_needing_post",
        "mark_fcc_els_application_posted",
        {"file_number": "F1"},
        message_id=7,
    )

    await orchestrator._process_fcc_els_applications(["chat-a", "chat-b"])

    assert marks == [("F1", "7,7")]
