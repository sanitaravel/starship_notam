"""Preservation tests for the FCC ELS duplicate incomplete-then-complete post bugfix.

Feature: fcc-els-duplicate-incomplete-post

**Property 2: Preservation** — Non-Deferred And Non-FCC-ELS Behavior Unchanged.

These tests capture the BASELINE behavior that the fix (task 3, gating
post-eligibility on a non-empty detail) must NOT change. They are written and
run against the UNFIXED code following the observation-first methodology: every
assertion below reflects behavior *observed today*, so the whole file is
EXPECTED TO PASS on the unfixed code. Task 3.3 re-runs it to prove the fix
introduced no regression.

The non-bug condition (``isBugCondition`` returns false, from the design) covers:
  - applications first seen with a populated detail (3.1),
  - already-posted applications re-scraped with no meaningful change (3.2),
  - genuinely new populated applications (new ``file_number``) (3.3),
  - the full set of rendered header fields plus the "Открыть заявку" link (3.4),
  - all non-FCC-ELS content: NOTAM / FAA / beach / road (3.5), which does not
    touch the modified query.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**
"""

from __future__ import annotations

import sqlite3

from hypothesis import HealthCheck, given, settings, strategies as st

from starship_notam.bot import formatting
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


# The two detail keys the formatter renders inside the expandable blockquote:
# the STA_Print "purpose of operation" field and the parser's "Explanation" key.
_PURPOSE_KEY = "Please explain the purpose of operation"
_EXPLANATION_KEY = "Explanation"


# Hypothesis strategies -----------------------------------------------------
# Ordinary, non-empty text for header fields (printable ASCII avoids surrogate
# and control-character noise while still varying content).
_field_text = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    min_size=1,
    max_size=15,
)

# Non-empty free text for the purpose / explanation detail values. These must be
# non-whitespace so the formatter renders them (it strips and drops blanks).
_detail_value = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    min_size=1,
    max_size=30,
)

# Any plausible file_number shape.
_FILE_NUMBER = st.from_regex(r"[0-9]{3,4}-EX-ST-20[0-9]{2}", fullmatch=True)


@st.composite
def _populated_app_strategy(draw, file_number=None):
    """Generate an application dict carrying a fully populated detail.

    "Populated" means the detail dict contains at least the purpose and
    explanation fields, so this is squarely a non-bug (must-preserve) input.
    """
    fn = file_number if file_number is not None else draw(_FILE_NUMBER)
    return {
        "file_number": fn,
        "application_seq": draw(_field_text),
        "applicant_name": draw(_field_text),
        "call_sign": draw(_field_text),
        "receipt_date": "01/01/2026",
        "status": draw(_field_text),
        "status_date": "01/15/2026",
        "current_detail_url": (
            "/oetcf/els/reports/STA_Print.cfm?mode=current&application_seq=153213"
        ),
        "detail": {
            _PURPOSE_KEY: draw(_detail_value),
            _EXPLANATION_KEY: draw(_detail_value),
        },
    }


# ---------------------------------------------------------------------------
# 3.1 — An application first seen with a populated detail is post-eligible
#       and its message is complete.
# ---------------------------------------------------------------------------
@_DB_SETTINGS
@given(app=_populated_app_strategy())
def test_populated_first_appearance_is_post_eligible_and_complete(
    tmp_path_factory, app
):
    # Feature: fcc-els-duplicate-incomplete-post, Property 2: Preservation
    """Saving an app with a populated detail on first appearance makes it
    post-eligible, and the single eligible row renders a complete message
    (purpose + explanation present). Baseline behavior — Requirement 3.1."""
    db = str(tmp_path_factory.mktemp("populated_first") / "notams.db")

    save_fcc_els_application(app, db)

    needing = get_fcc_els_applications_needing_post(db)
    eligible = [r for r in needing if r["file_number"] == app["file_number"]]
    assert len(eligible) == 1, (
        f"populated-first app {app['file_number']!r} should be post-eligible "
        "exactly once (Req 3.1)"
    )

    rendered = format_fcc_els_application(eligible[0])
    assert "Цель эксплуатации" in rendered
    assert "Обоснование" in rendered


# ---------------------------------------------------------------------------
# 3.2 — A no-change re-scrape of an already-posted application is NOT re-posted
#       and triggers no DB update.
# ---------------------------------------------------------------------------
@_DB_SETTINGS
@given(app=_populated_app_strategy())
def test_no_change_rescrape_is_not_reposted(tmp_path_factory, app):
    # Feature: fcc-els-duplicate-incomplete-post, Property 2: Preservation
    """Saving a populated app, marking it posted, then saving the identical
    payload again leaves telegram_posted = 1, changes no stored field, and does
    not make the app post-eligible again. Baseline behavior — Requirement 3.2."""
    db = str(tmp_path_factory.mktemp("no_change") / "notams.db")

    save_fcc_els_application(app, db)
    mark_fcc_els_application_posted(app["file_number"], "msg-1", db)

    before = _read_row(db, app["file_number"])
    assert before["telegram_posted"] == 1

    # Re-scrape with an identical (freshly built) payload — no meaningful change.
    save_fcc_els_application(dict(app), db)

    after = _read_row(db, app["file_number"])
    # No DB update: every stored field (incl. payload_hash / updated_at) is
    # unchanged and the posted flag is preserved.
    assert after == before
    assert after["telegram_posted"] == 1

    # And it is NOT returned as needing a post.
    needing = get_fcc_els_applications_needing_post(db)
    assert app["file_number"] not in {r["file_number"] for r in needing}


# ---------------------------------------------------------------------------
# 3.3 — A genuinely new file_number with a populated detail is post-eligible.
# ---------------------------------------------------------------------------
@_DB_SETTINGS
@given(data=st.data())
def test_new_populated_file_numbers_are_all_post_eligible(
    tmp_path_factory, data
):
    # Feature: fcc-els-duplicate-incomplete-post, Property 2: Preservation
    """Saving several distinct new file_numbers, each with a populated detail,
    makes every one of them post-eligible. Baseline behavior — Requirement
    3.3."""
    db = str(tmp_path_factory.mktemp("new_populated") / "notams.db")

    # Build a set of distinct file_numbers so each save is a genuinely new app.
    count = data.draw(st.integers(min_value=1, max_value=5))
    file_numbers = [f"NEW-{i:03d}-EX-ST-2026" for i in range(count)]

    for fn in file_numbers:
        app = data.draw(_populated_app_strategy(file_number=fn))
        save_fcc_els_application(app, db)

    needing = get_fcc_els_applications_needing_post(db)
    returned = {r["file_number"] for r in needing}
    assert returned == set(file_numbers), (
        "every new populated application should be post-eligible (Req 3.3)"
    )


# ---------------------------------------------------------------------------
# 3.4 — Header fields and the "Открыть заявку" link render as today.
# ---------------------------------------------------------------------------
@_DB_SETTINGS
@given(app=_populated_app_strategy())
def test_header_fields_and_link_render(tmp_path_factory, app):
    # Feature: fcc-els-duplicate-incomplete-post, Property 2: Preservation
    """format_fcc_els_application renders every header label — Заявитель,
    Номер дела, Позывной, Статус, Дата получения, Дата статуса — and the
    "Открыть заявку" link (a current_detail_url is always supplied). Baseline
    behavior — Requirement 3.4."""
    rendered = format_fcc_els_application(app)

    for label in (
        "Заявитель",
        "Номер дела",
        "Позывной",
        "Статус",
        "Дата получения",
        "Дата статуса",
    ):
        assert label in rendered, f"header label {label!r} missing (Req 3.4)"

    assert "Открыть заявку" in rendered


def test_header_fields_and_link_render_concrete_example():
    """Concrete characterization of the rendered header + link for a known
    application (pins the exact labels/link text — Requirement 3.4)."""
    app = {
        "applicant_name": "Space Exploration Technologies Corp.",
        "file_number": "1514-EX-ST-2026",
        "call_sign": "WX2XAB",
        "status": "Granted",
        "receipt_date": "01/01/2026",
        "status_date": "01/15/2026",
        "detail_json": {
            _PURPOSE_KEY: "Starship flight test telemetry.",
            _EXPLANATION_KEY: "Experimental STA supporting an integrated flight test.",
        },
        "current_detail_url": (
            "/oetcf/els/reports/STA_Print.cfm?mode=current&application_seq=153213"
        ),
    }
    out = format_fcc_els_application(app)

    assert out.startswith("<b>Новая заявка FCC ELS</b>")
    assert "<b>Заявитель:</b> Space Exploration Technologies Corp." in out
    assert "<b>Номер дела:</b> 1514-EX-ST-2026" in out
    assert "<b>Позывной:</b> WX2XAB" in out
    assert "<b>Статус:</b> Granted" in out
    assert "<b>Дата получения:</b> 01.01.2026" in out
    assert "<b>Дата статуса:</b> 15.01.2026" in out
    assert (
        '<a href="https://apps.fcc.gov/oetcf/els/reports/STA_Print.cfm'
        "?mode=current&amp;application_seq=153213\">Открыть заявку</a>" in out
    )


# ---------------------------------------------------------------------------
# 3.5 — Non-FCC-ELS content (NOTAM / FAA / beach / road) is untouched by the
#       modified query. The formatters are pure and never touch the DB, so we
#       characterize their output to confirm the fix (which only edits the FCC
#       ELS eligibility query) leaves them unchanged.
# ---------------------------------------------------------------------------
def test_faa_activity_formatting_unchanged():
    """FAA planned-activity formatting is unaffected by the FCC ELS fix
    (Req 3.5)."""
    activity = {
        "mission": "Starship Flight Test",
        "primary_window": "06/24/26 0248Z-0531Z",
        "backup_window": "06/25/26 0248Z-0531Z",
    }
    out = formatting.format_faa_activity(activity)

    assert "<b>FAA Planned Activity</b>" in out
    assert "<b>Миссия:</b> Starship Flight Test" in out
    assert "<b>Основное окно:</b> 24.06.2026 02:48–05:31 UTC" in out
    assert "<b>Запасное окно:</b> 25.06.2026 02:48–05:31 UTC" in out


def test_road_alert_formatting_unchanged():
    """Road-delay alert formatting is unaffected by the FCC ELS fix (Req 3.5)."""
    alert = {
        "origin": "Production",
        "destination": "Pad",
        "start_utc": "2026-06-25T04:59:00+00:00",
        "end_utc": "2026-06-25T06:00:00+00:00",
    }
    out = formatting.format_road_alert(alert)

    assert "<b>🚧 Ограничение движения</b>" in out
    assert "<b>Маршрут:</b> Starfactory → Пусковые площадки" in out
    assert (
        "<b>Время:</b> 25.06.2026 04:59 UTC – 25.06.2026 06:00 UTC" in out
    )


def test_beach_alert_formatting_unchanged():
    """Beach-closure alert formatting is unaffected by the FCC ELS fix
    (Req 3.5)."""
    alert = {
        "periods_json": [
            {
                "start_utc": "2026-07-08T18:00:00+00:00",
                "end_utc": "2026-07-09T04:00:00+00:00",
            },
        ],
    }
    out = formatting.format_beach_alert(alert)

    assert "<b>🏖️ Перекрытие пляжа</b>" in out
    assert (
        "<b>Основной период:</b> 08.07.2026 18:00 UTC – 09.07.2026 04:00 UTC"
        in out
    )


def test_notam_caption_formatting_unchanged(sample_parsed_notam):
    """NOTAM caption formatting is unaffected by the FCC ELS fix (Req 3.5)."""
    out = formatting.build_notam_caption("2026_A0123_26", sample_parsed_notam)

    assert out.startswith("<b>Новый NOTAM</b>")
    assert "<b>Код NOTAM:</b> 2026/A0123/26" in out
    assert "STARSHIP SUPER HEAVY LAUNCH OPERATIONS." in out
