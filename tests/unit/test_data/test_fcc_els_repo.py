"""Unit + property tests for FCC ELS persistence (``data.fcc_els_repo``).

Exercises save/query/mark round-trips against isolated temporary SQLite
databases. Imports only the data layer (standard-library dependencies only),
satisfying Requirement 9.2.

Property tests use Hypothesis (``@settings(max_examples=100)``) and are tagged
``# Feature: fcc-els-scraper, Property N: <text>``.

Covers Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 6.4, 7.1.
"""

from __future__ import annotations

import sqlite3

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

# These property tests exercise real SQLite file I/O (init_db creates the full
# schema on every save), so individual examples take longer than Hypothesis's
# default 200ms deadline and input generation can trip the too_slow check. The
# behaviour under test is I/O-bound, not compute-bound, so we disable the
# deadline and the timing/generation health checks rather than shrink coverage.
_DB_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

from starship_notam.data import fcc_els_repo
from starship_notam.data.fcc_els_repo import (
    get_fcc_els_applications_needing_post,
    mark_fcc_els_application_posted,
    save_fcc_els_application,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
# The ordered field keys that make up an application dict (excluding ``detail``,
# which is handled separately so we can vary its key order too).
_SCALAR_FIELDS = [
    "file_number",
    "application_seq",
    "applicant_name",
    "call_sign",
    "receipt_date",
    "status",
    "status_date",
    "current_detail_url",
]


def _app(file_number="0123-EX-ST-2025", **overrides):
    """Build a representative application dict with sensible defaults."""
    app = {
        "file_number": file_number,
        "application_seq": "12345",
        "applicant_name": "Space Exploration Technologies Corp.",
        "call_sign": "",
        "receipt_date": "01/01/2025",
        "status": "Granted",
        "status_date": "01/15/2025",
        "current_detail_url": (
            "https://apps.fcc.gov/oetcf/els/reports/STA_Print.cfm"
            "?mode=current&application_seq=12345"
        ),
        "detail": {"Frequency": "2000 MHz", "Power": "10 W"},
    }
    app.update(overrides)
    return app


def _read_row(db_path, file_number):
    """Return the stored row (as a dict) for *file_number*, or None."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM fcc_els_applications WHERE file_number = ?",
            (file_number,),
        )
        row = cur.fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def _count_rows(db_path, file_number):
    """Return the number of rows stored for *file_number*."""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM fcc_els_applications WHERE file_number = ?",
            (file_number,),
        )
        return cur.fetchone()[0]
    finally:
        conn.close()


# Hypothesis strategies -----------------------------------------------------
_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)), min_size=0, max_size=20
)
_nonempty_text = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    min_size=1,
    max_size=15,
)


@st.composite
def _app_strategy(draw, file_number="0123-EX-ST-2025"):
    """Generate a valid application dict with arbitrary field content."""
    detail_keys = draw(
        st.lists(_nonempty_text, min_size=0, max_size=5, unique=True)
    )
    detail = {k: draw(_text) for k in detail_keys}
    return {
        "file_number": file_number,
        "application_seq": draw(_text),
        "applicant_name": draw(_text),
        "call_sign": draw(_text),
        "receipt_date": draw(_text),
        "status": draw(_text),
        "status_date": draw(_text),
        "current_detail_url": draw(_text),
        "detail": detail,
    }


# ---------------------------------------------------------------------------
# Task 4.3 — Property tests
# ---------------------------------------------------------------------------
@_DB_SETTINGS
@given(data=_app_strategy())
def test_payload_hash_is_key_order_independent(tmp_path_factory, data):
    # Feature: fcc-els-scraper, Property 8: Payload hash is key-order independent
    """Two dicts with identical content but different key insertion order
    produce the same stored payload_hash (Req 5.2)."""
    # Build a second dict with the scalar keys inserted in reverse order and
    # the detail dict rebuilt in reverse key order.
    reordered = {}
    for key in reversed(_SCALAR_FIELDS):
        reordered[key] = data[key]
    reordered["detail"] = {
        k: data["detail"][k] for k in reversed(list(data["detail"].keys()))
    }

    db1 = str(tmp_path_factory.mktemp("h1") / "notams.db")
    db2 = str(tmp_path_factory.mktemp("h2") / "notams.db")

    save_fcc_els_application(data, db1)
    save_fcc_els_application(reordered, db2)

    hash1 = _read_row(db1, data["file_number"])["payload_hash"]
    hash2 = _read_row(db2, data["file_number"])["payload_hash"]

    assert hash1 == hash2


@_DB_SETTINGS
@given(data=_app_strategy())
def test_resaving_unchanged_application_never_reflags(tmp_path_factory, data):
    # Feature: fcc-els-scraper, Property 9: Re-saving an unchanged application never re-flags it
    """After marking posted, saving an identical app leaves telegram_posted=1
    and every stored field + payload_hash unchanged (Req 5.4)."""
    db = str(tmp_path_factory.mktemp("unchanged") / "notams.db")

    save_fcc_els_application(data, db)
    mark_fcc_els_application_posted(data["file_number"], "msg-1", db)

    before = _read_row(db, data["file_number"])
    assert before["telegram_posted"] == 1

    # Save an identical (freshly built) dict again.
    save_fcc_els_application(dict(data), db)

    after = _read_row(db, data["file_number"])
    assert after["telegram_posted"] == 1
    assert after == before


@_DB_SETTINGS
@given(data=_app_strategy())
def test_changed_application_is_reflagged(tmp_path_factory, data):
    # Feature: fcc-els-scraper, Property 10: A changed application is re-flagged for posting
    """Saving a variant with any changed field (including inside detail) resets
    telegram_posted to 0, refreshes updated_at, and stores a new hash (Req 5.5)."""
    db = str(tmp_path_factory.mktemp("changed") / "notams.db")

    save_fcc_els_application(data, db)
    mark_fcc_els_application_posted(data["file_number"], "msg-1", db)

    before = _read_row(db, data["file_number"])
    assert before["telegram_posted"] == 1

    # Produce a genuinely different payload: mutate the status AND the detail.
    changed = dict(data)
    changed["status"] = (data["status"] or "") + "-CHANGED"
    new_detail = dict(data["detail"])
    new_detail["__extra__"] = "new-value"
    changed["detail"] = new_detail

    save_fcc_els_application(changed, db)

    after = _read_row(db, data["file_number"])
    assert after["telegram_posted"] == 0
    assert after["payload_hash"] != before["payload_hash"]
    # updated_at is refreshed (>= previous, and created_at preserved).
    assert after["updated_at"] >= before["updated_at"]
    assert after["created_at"] == before["created_at"]


@_DB_SETTINGS
@given(
    apps=st.lists(_app_strategy(), min_size=1, max_size=6),
)
def test_file_number_uniqueness(tmp_path_factory, apps):
    # Feature: fcc-els-scraper, Property 11: File number uniqueness
    """After any sequence of saves with the same file_number, exactly one row
    exists for that file_number (Req 5.1, 6.4)."""
    db = str(tmp_path_factory.mktemp("uniq") / "notams.db")

    file_number = "SAME-FILE-NUMBER"
    for app in apps:
        app = dict(app)
        app["file_number"] = file_number
        save_fcc_els_application(app, db)

    assert _count_rows(db, file_number) == 1


@_DB_SETTINGS
@given(
    posted_mask=st.lists(st.booleans(), min_size=1, max_size=8),
)
def test_needing_post_query_returns_exactly_unposted_set(
    tmp_path_factory, posted_mask
):
    # Feature: fcc-els-scraper, Property 12: Needing-post query returns exactly the unposted set
    """Given saved apps with an arbitrary subset marked posted, the needing-post
    query returns exactly those with telegram_posted=0 (Req 7.1)."""
    db = str(tmp_path_factory.mktemp("needing") / "notams.db")

    expected_unposted = set()
    for i, is_posted in enumerate(posted_mask):
        file_number = f"FILE-{i:03d}"
        save_fcc_els_application(_app(file_number=file_number), db)
        if is_posted:
            mark_fcc_els_application_posted(file_number, f"msg-{i}", db)
        else:
            expected_unposted.add(file_number)

    needing = get_fcc_els_applications_needing_post(db)
    returned = {row["file_number"] for row in needing}

    assert returned == expected_unposted
    # Every returned row is genuinely unposted.
    assert all(row["telegram_posted"] == 0 for row in needing)


# ---------------------------------------------------------------------------
# Task 4.4 — Example tests
# ---------------------------------------------------------------------------
def test_insert_sets_posted_zero_timestamps_and_hash(db_path):
    """A fresh insert sets telegram_posted=0, populates created_at/updated_at,
    and stores a non-empty payload_hash (Req 5.3)."""
    app = _app()
    save_fcc_els_application(app, db_path)

    row = _read_row(db_path, app["file_number"])

    assert row is not None
    assert row["telegram_posted"] == 0
    assert row["telegram_posted_at"] is None
    assert row["telegram_message_id"] is None
    assert row["created_at"]
    assert row["updated_at"]
    assert row["created_at"] == row["updated_at"]
    assert row["payload_hash"]
    # detail is serialized to detail_json.
    assert row["detail_json"]


def test_mark_posted_populates_three_telegram_columns(db_path):
    """mark_fcc_els_application_posted sets telegram_posted=1, a non-null
    telegram_posted_at, and the telegram_message_id (Req 5.6)."""
    app = _app()
    save_fcc_els_application(app, db_path)

    mark_fcc_els_application_posted(app["file_number"], "12345,67890", db_path)

    row = _read_row(db_path, app["file_number"])

    assert row["telegram_posted"] == 1
    assert row["telegram_posted_at"] is not None
    assert row["telegram_message_id"] == "12345,67890"


def test_save_rolls_back_and_reraises_on_db_error_leaving_no_partial_row(
    db_path, monkeypatch
):
    """A forced DB error during save triggers rollback + re-raise and leaves no
    partial row behind (Req 5.7)."""

    class _FailingCommitConnection:
        """Wraps a real connection but raises when commit() is called.

        Delegates everything else so init_db (which uses a *different*
        get_connection reference) is unaffected and the save's own INSERT is
        attempted before commit blows up, exercising the rollback path.
        """

        def __init__(self, inner):
            self._inner = inner

        def commit(self):
            raise sqlite3.OperationalError("forced commit failure")

        def __getattr__(self, name):
            return getattr(self._inner, name)

    real_get_connection = fcc_els_repo.get_connection

    def fake_get_connection(path=None):
        return _FailingCommitConnection(real_get_connection(path))

    # Patch only the repo module's reference so init_db still works normally.
    monkeypatch.setattr(fcc_els_repo, "get_connection", fake_get_connection)

    app = _app()
    with pytest.raises(sqlite3.OperationalError):
        save_fcc_els_application(app, db_path)

    # Restore so we can read cleanly.
    monkeypatch.setattr(fcc_els_repo, "get_connection", real_get_connection)

    # The failed insert was rolled back: no partial row remains.
    assert _count_rows(db_path, app["file_number"]) == 0
