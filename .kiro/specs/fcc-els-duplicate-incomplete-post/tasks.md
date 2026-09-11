# Implementation Plan

- [ ] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - Empty-Detail Application Is Post-Eligible And Re-Posts When Populated
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the bug exists (empty-detail apps are post-eligible and the empty→populated transition re-posts the same `file_number`)
  - **Scoped PBT Approach**: Scope the property to the concrete empty-detail representations that trigger the bug: `detail == {}` (persisted as `detail_json == '{}'`), plus `NULL`, `''`, and whitespace-only `detail_json`, paired with any `file_number`
  - Using an in-memory / temp SQLite DB, drive the persistence + post-eligibility path directly via `save_fcc_els_application` and `get_fcc_els_applications_needing_post` (from `starship_notam/data/fcc_els_repo.py`)
  - Bug condition (from design `isBugCondition` / `isEmptyDetail`): the application is post-eligible while its detail is empty (`detail IS NULL OR detail == {} OR json.dumps(detail) == '{}'`) and later becomes populated
  - Assert (encodes Expected Behavior 2.1/2.3): after saving an app with `detail == {}`, it should NOT appear in `get_fcc_els_applications_needing_post`; then after saving the same `file_number` with a populated detail, it should appear exactly once
  - Also assert the incomplete-message symptom: `format_fcc_els_application` (in `starship_notam/bot/formatting.py`) on the empty-detail app omits "Цель эксплуатации" and "Обоснование"
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS (this is correct - it proves the bug exists: the empty-detail row is returned as post-eligible, and the empty→populated save resets `telegram_posted` to 0 so the row is returned a second time)
  - Document counterexamples found (e.g., "save(1514-EX-ST-2026, detail={}) is returned by get_fcc_els_applications_needing_post; after save with populated detail, telegram_posted resets to 0 and the same file_number is returned again → two posts")
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3_

- [ ] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Non-Deferred And Non-FCC-ELS Behavior Unchanged
  - **IMPORTANT**: Follow observation-first methodology
  - Non-bug condition (from design): all inputs where `isBugCondition` returns false — applications first seen with a populated detail, already-posted apps re-scraped with no change, genuinely new populated apps, header/link rendering, and all non-FCC-ELS content
  - Observe behavior on UNFIXED code first, then write property-based tests (where practical) capturing that behavior:
    - Observe: saving an app with a populated detail on first appearance makes it post-eligible via `get_fcc_els_applications_needing_post` (3.1)
    - Observe: saving a populated app, marking it posted via `mark_fcc_els_application_posted`, then saving the identical payload again leaves `telegram_posted = 1` and triggers no DB update (3.2)
    - Observe: saving a new `file_number` with a populated detail makes it post-eligible (3.3)
    - Observe: `format_fcc_els_application` renders Заявитель, Номер дела, Позывной, Статус, Дата получения, Дата статуса and the "Открыть заявку" link (3.4)
    - Observe: NOTAM, FAA, beach, and road eligibility/formatting paths (3.5) are untouched by the modified query
  - Write property-based tests: generate random applications with populated details and assert post-eligibility and complete rendering are unchanged; generate no-change re-scrape sequences and assert no re-post
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (this confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [ ] 3. Fix for duplicate incomplete-then-complete FCC ELS post

  - [ ] 3.1 Gate post-eligibility on non-empty detail
    - In `get_fcc_els_applications_needing_post` (`starship_notam/data/fcc_els_repo.py`), keep the existing `telegram_posted = 0` filter and `ORDER BY created_at`, and additionally exclude rows whose detail is empty: `detail_json IS NULL OR TRIM(detail_json) = '' OR TRIM(detail_json) = '{}'`
    - Add a small helper (e.g. `_is_empty_detail_json(value)`) that mirrors the SQL predicate, as a single source of truth for the "empty detail" test and for use in tests
    - Do NOT change `save_fcc_els_application`: the empty→populated transition still bumps `payload_hash` and resets `telegram_posted = 0`; because the empty-detail row was never posted, the now-populated row is simply posted once
    - No change required in `_process_fcc_els_applications` (`starship_notam/bot/orchestrator.py`) since posting is driven entirely by the gated query
    - _Bug_Condition: isBugCondition(X) = isEmptyDetail(X.detail_at_first_post) AND becomesPopulated(X.detail_on_later_scrape), from design_
    - _Expected_Behavior: exactly one post per file_number, and that post includes "Цель эксплуатации" and "Обоснование" (Property 1), from design_
    - _Preservation: Preservation Requirements from design (populated-first, no-change re-scrape, new populated app, header/link rendering, other content types unaffected)_
    - _Requirements: 2.1, 2.2, 2.3_

  - [ ] 3.2 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Single Complete Post For Deferred Application
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior
    - When this test passes, it confirms the expected behavior is satisfied: the empty-detail save is deferred (not returned by the eligibility query), and the populated save is returned exactly once and, when formatted, includes both detail fields
    - Run bug condition exploration test from step 1
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - _Requirements: 2.1, 2.2, 2.3_

  - [ ] 3.3 Verify preservation tests still pass
    - **Property 2: Preservation** - Non-Deferred And Non-FCC-ELS Behavior Unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run preservation property tests from step 2
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions for populated-first posting, no-change skip, new populated apps, header/link rendering, and other content types)
    - Confirm all tests still pass after fix (no regressions)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [ ] 4. Add integration tests for the full FCC ELS flow
  - Full FCC ELS flow: a scrape sequence (empty then populated) driven through `_process_fcc_els_applications` results in a single complete Telegram message per `file_number`
  - Verify the deferred application is eventually posted exactly once its detail populates on a later cycle
  - Mixed run: an FCC ELS empty-detail deferral in the same cycle as NOTAM/FAA/beach/road processing does not disturb those pipelines
  - _Requirements: 2.1, 2.2, 2.3, 3.5_

- [ ] 5. Checkpoint - Ensure all tests pass
  - Run the full test suite (unit, property-based, and integration) and ensure all tests pass
  - Confirm Property 1 (single complete post) passes and Property 2 (preservation) passes
  - Ensure all tests pass, ask the user if questions arise
