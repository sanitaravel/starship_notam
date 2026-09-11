"""Bug condition exploration test for the FCC ELS duplicate incomplete-then-complete post bug.

Feature: fcc-els-duplicate-incomplete-post

This test encodes the EXPECTED (fixed) behavior described in the bugfix design:
an FCC ELS application whose detail is empty (``detail == {}`` / ``detail_json``
that is NULL / '' / whitespace / '{}') must NOT be post-eligible (it should be
deferred), and once its detail is populated it must become post-eligible EXACTLY
once — never producing a duplicate incomplete-then-complete pair.

Because this is a *bug condition exploration* test run against the UNFIXED code,
it is EXPECTED TO FAIL. The failure confirms the bug exists:
    - ``get_fcc_els_applications_needing_post`` currently returns empty-detail
      rows (``WHERE telegram_posted = 0`` ignores detail completeness), so an
      incomplete message would be posted.
    - The empty->populated ``save_fcc_els_application`` transition changes
      ``payload_hash`` and resets ``telegram_posted`` to 0, so the same
      ``file_number`` is returned a second time -> a duplicate post.

DO NOT fix the test or the production code from here. The failure is the success
condition for this task.

**Property 1: Bug Condition** — Empty-Detail Application Is Post-Eligible And
Re-Posts When Populated.

**Validates: Requirements 2.1, 2.3**
"""

from __future__ import annotations

import sqlite3

from hypothesis import HealthCheck, given, settings, strategies as st

from starship_notam.bot.formatting import format_fcc_els_application
from starship_notam.data.fcc_els_repo import (
    get_fcc_els_applications_needing_post,
    mark_fcc_els_application_posted,
    save_fcc_els_application,
)

# These property examples exercise real SQLite file I/O (init_db rebuilds the
# full schema on every save), so individual examples exceed Hypothesis's default
# 200ms deadline and generation can trip the too_slow health check. The work is
# I/O-bound, not compute-bound, so disable the deadline / timing checks rather
# than shrink coverage. Mirrors the existing repo test settings.
_DB_SETTINGS = settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
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


def _force_detail_json(db_path, file_number, raw_value):
    """Overwrite ``detail_json`` for a row directly.

    ``save_fcc_els_application`` always serialises ``detail`` to a canonical
    JSON string (an empty/missing detail becomes ``'{}'``), so it cannot produce
    the NULL / '' / whitespace-only empty-detail representations that also occur
    in the wild (legacy rows, partial writes). We first save through the real
    code path (to exercise schema + hashing) and then patch the column to the
    concrete empty representation under test.
    """
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE fcc_els_applications SET detail_json = ? WHERE file_number = ?",
            (raw_value, file_number),
        )
        conn.commit()
    finally:
        conn.close()


def _populated_app(file_number):
    """A representative application dict carrying a fully populated detail."""
    return {
        "file_number": file_number,
        "application_seq": "153213",
        "applicant_name": "Space Exploration Technologies Corp.",
        "call_sign": "WX2XAB",
        "receipt_date": "01/01/2026",
        "status": "Granted",
        "status_date": "01/15/2026",
        "current_detail_url": (
            "/oetcf/els/reports/STA_Print.cfm?mode=current&application_seq=153213"
        ),
        "detail": {
            "Please explain the purpose of operation": "Starship flight test telemetry.",
            "Explanation": "Experimental STA supporting an integrated flight test.",
        },
    }


def _empty_app(file_number):
    """A representative application dict whose detail is an empty dict."""
    app = _populated_app(file_number)
    app["detail"] = {}
    return app


# The concrete empty-detail representations that trigger the bug. ``'{}'`` is
# what ``save_fcc_els_application`` persists for ``detail == {}``; NULL / '' /
# whitespace-only cover the other in-the-wild empty forms named in the design's
# ``isEmptyDetail`` / the fix's SQL predicate.
_EMPTY_DETAIL_JSON = st.sampled_from([None, "", "   ", "\t", "\n  ", "{}"])

# Any plausible file_number shape, including the reported instance.
_FILE_NUMBER = st.one_of(
    st.just("1514-EX-ST-2026"),
    st.from_regex(r"[0-9]{3,4}-EX-ST-20[0-9]{2}", fullmatch=True),
)


# ---------------------------------------------------------------------------
# Property 1: Bug Condition — empty-detail deferral + single populated post
# ---------------------------------------------------------------------------
@_DB_SETTINGS
@given(file_number=_FILE_NUMBER, empty_json=_EMPTY_DETAIL_JSON)
def test_empty_detail_deferred_then_single_post_when_populated(
    tmp_path_factory, file_number, empty_json
):
    # Feature: fcc-els-duplicate-incomplete-post, Property 1: Bug Condition
    """Empty-detail apps must NOT be post-eligible; once populated the same
    file_number must become post-eligible exactly once (no duplicate).

    Validates: Requirements 2.1, 2.3.

    EXPECTED TO FAIL on unfixed code:
      - the empty-detail row IS returned by get_fcc_els_applications_needing_post
        (Requirement 2.1 violated), and
      - after posting it and then saving a populated detail, telegram_posted is
        reset to 0 so the row is returned AGAIN — a duplicate (Requirement 2.3
        violated).
    """
    db = str(tmp_path_factory.mktemp("empty_defer") / "notams.db")

    # 1) Save the application while its detail is empty, then force the concrete
    #    empty representation under test (NULL / '' / whitespace / '{}').
    save_fcc_els_application(_empty_app(file_number), db)
    _force_detail_json(db, file_number, empty_json)

    # Requirement 2.1: an empty-detail application must NOT be post-eligible.
    needing_while_empty = get_fcc_els_applications_needing_post(db)
    empty_eligible = [r for r in needing_while_empty if r["file_number"] == file_number]
    assert empty_eligible == [], (
        f"empty-detail app {file_number!r} (detail_json={empty_json!r}) is "
        "post-eligible but should be deferred (Req 2.1)"
    )

    # Simulate the orchestrator posting whatever was eligible while empty. On the
    # fixed system nothing was eligible, so nothing is marked. On the buggy
    # system the incomplete row was eligible and would be posted here.
    for row in empty_eligible:
        mark_fcc_els_application_posted(row["file_number"], "incomplete-msg", db)

    # 2) A later scrape populates the detail for the SAME file_number.
    save_fcc_els_application(_populated_app(file_number), db)

    # Requirement 2.3: exactly one post for this file_number — it must appear
    # exactly once across the empty phase (0 times) and the populated phase.
    needing_after_populate = get_fcc_els_applications_needing_post(db)
    populated_eligible = [
        r for r in needing_after_populate if r["file_number"] == file_number
    ]
    total_eligible_appearances = len(empty_eligible) + len(populated_eligible)
    assert total_eligible_appearances == 1, (
        f"file_number {file_number!r} became post-eligible "
        f"{total_eligible_appearances} times (empty phase: {len(empty_eligible)}, "
        f"populated phase: {len(populated_eligible)}); expected exactly 1 "
        "complete post (Req 2.3)"
    )

    # The single eligible row must carry the populated detail so the post is
    # complete (purpose + explanation present in the rendered message).
    (row,) = populated_eligible
    rendered = format_fcc_els_application(row)
    assert "Цель эксплуатации" in rendered
    assert "Обоснование" in rendered


# ---------------------------------------------------------------------------
# Symptom: the incomplete message omits the detail fields
# ---------------------------------------------------------------------------
@_DB_SETTINGS
@given(file_number=_FILE_NUMBER, empty_json=_EMPTY_DETAIL_JSON)
def test_empty_detail_message_omits_purpose_and_explanation(
    tmp_path_factory, file_number, empty_json
):
    # Feature: fcc-els-duplicate-incomplete-post, Property 1: Bug Condition
    """Characterises the incomplete-message symptom: an empty-detail app renders
    WITHOUT "Цель эксплуатации" / "Обоснование".

    This is the message that the unfixed system posts (because the empty row is
    post-eligible). The whole point of deferral is that this message is never
    sent; the assertion below documents its incompleteness.
    """
    db = str(tmp_path_factory.mktemp("empty_msg") / "notams.db")

    save_fcc_els_application(_empty_app(file_number), db)
    _force_detail_json(db, file_number, empty_json)

    row = _read_row(db, file_number)
    rendered = format_fcc_els_application(row)

    assert "Цель эксплуатации" not in rendered
    assert "Обоснование" not in rendered
