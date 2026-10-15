"""Pending items are marked posted only when a Telegram send succeeded.

Regression test for fix-plan step 6: FAA activities, beach alerts and road
alerts used to be marked posted even when every send failed, so they were
silently lost. All five post types now share ``post_pending``.
"""

from __future__ import annotations

import asyncio

import pytest

from starship_notam.bot.orchestrator import faa, fcc_els, posting, starbase

# module, processor, "needing post" getter, mark function, item, expected mark args
CASES = [
    (
        faa,
        "process_faa_activities",
        "get_faa_activities_needing_post",
        "mark_faa_activity_posted",
        {"mission": "Starship Flight 15"},
        ("Starship Flight 15", "42"),
    ),
    (
        fcc_els,
        "process_fcc_els_applications",
        "get_fcc_els_applications_needing_post",
        "mark_fcc_els_application_posted",
        {"file_number": "0123-EX-ST-2026"},
        ("0123-EX-ST-2026", "42"),
    ),
    (
        faa,
        "process_faa_licenses",
        "get_faa_licenses_needing_post",
        "mark_faa_license_posted",
        {"doc_unique_id": "DRSDOCID1"},
        ("DRSDOCID1", "42"),
    ),
    (
        starbase,
        "process_beach_alerts",
        "get_beach_alerts_needing_post",
        "mark_beach_posted",
        {"alert_key": "beach-key"},
        ("beach-key",),
    ),
    (
        starbase,
        "process_road_alerts",
        "get_road_alerts_needing_post",
        "mark_road_posted",
        {"alert_key": "road-key"},
        ("road-key",),
    ),
]
IDS = [case[1] for case in CASES]


@pytest.fixture
def harness(monkeypatch):
    """Stub out scraping, formatting, sleeping and the DB; record marks."""
    marks: list[tuple] = []

    async def no_sleep(_seconds):
        pass

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    monkeypatch.setattr(faa, "fetch_faa_advisory", lambda: [])
    monkeypatch.setattr(fcc_els, "fetch_fcc_els_applications", lambda: [])
    monkeypatch.setattr(faa, "fetch_faa_license", lambda: None)
    for module, fmt in (
        (faa, "format_faa_activity"),
        (fcc_els, "format_fcc_els_application"),
        (faa, "format_faa_license"),
        (starbase, "format_beach_alert"),
        (starbase, "format_road_alert"),
    ):
        monkeypatch.setattr(module, fmt, lambda item: "text")

    def setup(module, getter, mark_fn, item, message_id):
        monkeypatch.setattr(module, getter, lambda db_path: [item])
        monkeypatch.setattr(
            module, mark_fn, lambda *args: marks.append(args[:-1])
        )

        async def fake_send(chat_id, text):
            return message_id

        monkeypatch.setattr(posting, "send_message", fake_send)

    return setup, marks


@pytest.mark.parametrize("module, processor, getter, mark_fn, item, expected", CASES, ids=IDS)
async def test_failed_send_leaves_item_unposted(
    harness, module, processor, getter, mark_fn, item, expected
):
    setup, marks = harness
    setup(module, getter, mark_fn, item, message_id=None)

    await getattr(module, processor)(["chat"])

    assert marks == []


@pytest.mark.parametrize("module, processor, getter, mark_fn, item, expected", CASES, ids=IDS)
async def test_successful_send_marks_item_posted(
    harness, module, processor, getter, mark_fn, item, expected
):
    setup, marks = harness
    setup(module, getter, mark_fn, item, message_id=42)

    await getattr(module, processor)(["chat"])

    assert marks == [expected]


async def test_message_ids_from_several_chats_are_joined(harness):
    setup, marks = harness
    setup(
        fcc_els,
        "get_fcc_els_applications_needing_post",
        "mark_fcc_els_application_posted",
        {"file_number": "F1"},
        message_id=7,
    )

    await fcc_els.process_fcc_els_applications(["chat-a", "chat-b"])

    assert marks == [("F1", "7,7")]
