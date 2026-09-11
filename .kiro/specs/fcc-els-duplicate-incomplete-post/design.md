# FCC ELS Duplicate Incomplete-Then-Complete Post Bugfix Design

## Overview

The FCC ELS bot can post the same application to Telegram twice: first an incomplete
message (missing "Цель эксплуатации" / purpose of operation and "Обоснование" / Explanation),
then a duplicate complete message once the detail page finally populates.

The root cause is a chain of three cooperating behaviors:

1. `fetch_fcc_els_applications` (the scraper) can return an application whose `detail` is an
   empty dict (`{}`) when the `STA_Print.cfm` detail page has not populated yet. The scraper
   only discards a row when detail retrieval/parsing *fails* (`detail is None`); a successfully
   parsed-but-empty page yields `detail == {}` and is kept.
2. `save_fcc_els_application` computes `payload_hash` over a payload that includes
   `detail_json`. On first appearance the row is inserted with `telegram_posted = 0`. When a
   later run populates the detail, `detail_json` changes from `'{}'` to a populated JSON string,
   so `payload_hash` changes, the "changes detected" branch fires, and `telegram_posted` is
   reset to `0`.
3. `_process_fcc_els_applications` (the orchestrator) posts everything returned by
   `get_fcc_els_applications_needing_post`, which selects all rows with `telegram_posted = 0`.
   The empty-detail row is posted once (incomplete), then the reset-to-zero row is posted again
   (complete) — two messages for the same `file_number`.

The fix strategy is minimal and targeted: **defer posting an application while its detail is
empty.** An application is only eligible to be posted once its `detail_json` represents a
non-empty detail. This means the incomplete message is never sent, so the later empty→populated
transition produces the single, complete post the user expects. All existing behavior for
applications that first appear with a populated detail — and for every other content type — is
untouched.

## Glossary

- **Bug_Condition (C)**: The condition that triggers the bug — an FCC ELS application is (or would
  be) posted to Telegram while its detail is still empty (`detail == {}` / `detail_json == '{}'`),
  so that a later run with a populated detail re-posts it.
- **Property (P)**: The desired behavior for buggy inputs — exactly one Telegram post per
  `file_number`, and that single post includes "Цель эксплуатации" and "Обоснование".
- **Preservation**: Existing behavior that must remain unchanged — first-appearance-with-detail
  posting, no-change skip/no-repost, genuinely-new-application posting, the full set of rendered
  header fields plus the "Открыть заявку" link, and all other content types (NOTAMs, FAA
  activities, beach alerts, road alerts).
- **detail / detail_json**: The `{label: value}` mapping parsed from the `STA_Print.cfm` detail
  page. In scraper output it is the `detail` key (a dict); persisted it is the `detail_json`
  column (a JSON string). "Empty detail" means `{}` / `'{}'`.
- **save_fcc_els_application**: The function in `starship_notam/data/fcc_els_repo.py` that upserts
  an application by `file_number`, computes `payload_hash`, and resets `telegram_posted` to 0 when
  the payload changes.
- **get_fcc_els_applications_needing_post**: The query in `starship_notam/data/fcc_els_repo.py`
  that returns rows with `telegram_posted = 0` for the orchestrator to post.
- **_process_fcc_els_applications**: The orchestrator step in `starship_notam/bot/orchestrator.py`
  that saves scraped apps and posts those needing posting.
- **telegram_posted**: The 0/1 flag column that determines whether an application still needs to
  be posted.

## Bug Details

### Bug Condition

The bug manifests when an FCC ELS application is persisted (and becomes post-eligible) while its
detail is still empty, and a later scrape populates that detail. The empty-detail state makes the
application post-eligible with an incomplete message, and the subsequent empty→populated transition
changes `payload_hash`, resets `telegram_posted` to 0, and re-posts the application as if new.

**Formal Specification:**
```
FUNCTION isBugCondition(X)
  INPUT: X of type FccElsApplication (as scraped/saved over time)
  OUTPUT: boolean

  // The bug is triggered when an application is post-eligible while its
  // detail is empty, so that a later run with a populated detail re-posts it.
  RETURN isEmptyDetail(X.detail_at_first_post)          // detail == {} at first post
         AND becomesPopulated(X.detail_on_later_scrape) // detail later populated
END FUNCTION

FUNCTION isEmptyDetail(detail)
  RETURN detail IS NULL
         OR detail == {}
         OR json.dumps(detail) == '{}'
END FUNCTION
```

### Examples

- **Reported instance** — file number `1514-EX-ST-2026` (application_seq 153213): posted at 20:02
  with `detail_json = '{}'` (message ids 735, 736), then posted again at 20:32 with fully
  populated detail (message ids 737, 738). `payload_hash` differed (`661420887be7...` vs
  `54b776f44ba...`), which re-triggered the post. Expected: a single post at 20:32 containing the
  purpose and explanation. **(bug)**
- An application first scraped with `detail == {}` (detail page not yet populated), never posted,
  then re-scraped with a populated detail. Expected: one post with complete detail, no incomplete
  precursor. **(bug)**
- An application scraped once with `detail == {}` and still empty on the next scrape (no change):
  should remain deferred and unposted, not posted incomplete. **(bug boundary — deferral case)**
- An application first scraped with a populated detail: should be posted exactly once with the
  complete message. **(not bug — must be preserved, see 3.1)**

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- An application first scraped with a populated detail continues to be saved and posted exactly
  once with the complete message (Requirement 3.1).
- An already-posted application re-scraped with no meaningful change continues to skip the DB
  update and is NOT re-posted (Requirement 3.2).
- A genuinely new application (new `file_number`) with a populated detail continues to be posted
  (Requirement 3.3).
- Every existing header field — Заявитель, Номер дела, Позывной, Статус, Дата получения, Дата
  статуса — and the "Открыть заявку" link continue to render as today (Requirement 3.4).
- Other content types (NOTAMs, FAA activities, beach alerts, road alerts) continue to be
  processed and posted exactly as today, unaffected by this fix (Requirement 3.5).

**Scope:**
All inputs that do NOT involve an FCC ELS application being post-eligible with an empty detail
should be completely unaffected by this fix. This includes:
- FCC ELS applications whose detail is already populated at the time they become post-eligible.
- FCC ELS applications that have already been posted (with a populated detail) and are re-scraped.
- All non-FCC-ELS content pipelines (NOTAMs, FAA activities, beach and road alerts).

**Note:** The expected correct behavior for buggy inputs (a single complete post) is defined in
the Correctness Properties section (Property 1). This section focuses on what must NOT change.

## Hypothesized Root Cause

Based on the bug description and the code, the contributing causes are:

1. **Scraper keeps empty-detail rows**: `fetch_fcc_els_applications` in
   `starship_notam/scrapers/fcc_els_fetcher.py` discards a row only when detail retrieval/parsing
   *fails* (`detail is None`). A page that parses to `{}` (not yet populated) is kept, so the
   application enters the pipeline with `detail == {}`.

2. **`detail_json` participates in the change hash**: `save_fcc_els_application` in
   `starship_notam/data/fcc_els_repo.py` includes `detail_json` in the `payload` that feeds
   `payload_hash`. The empty→populated transition therefore always changes the hash, triggers the
   "changes detected" branch, and resets `telegram_posted = 0`.

3. **Post-eligibility ignores detail completeness**: `get_fcc_els_applications_needing_post`
   selects every row with `telegram_posted = 0` regardless of whether its detail is populated, and
   `_process_fcc_els_applications` posts them all. Nothing gates posting on detail completeness,
   so the empty-detail row is posted incomplete and the reset row is posted again complete.

The primary lever for a minimal, low-regression fix is cause #3: **make an empty detail
non-post-eligible (defer it).** If the incomplete message is never sent, the later empty→populated
re-post has no incomplete precursor to duplicate, and the reset-to-zero mechanism harmlessly
produces the single complete post.

## Correctness Properties

Property 1: Bug Condition - Single Complete Post For Deferred Application

_For any_ input where the bug condition holds (`isBugCondition` returns true) — an application that
would previously have been post-eligible with an empty detail and is later populated — the fixed
system SHALL post that `file_number` exactly once, and that single Telegram message SHALL include
both "Цель эксплуатации" (purpose of operation) and "Обоснование" (Explanation).

**Validates: Requirements 2.1, 2.2, 2.3**

Property 2: Preservation - Non-Deferred And Non-FCC-ELS Behavior Unchanged

_For any_ input where the bug condition does NOT hold (`isBugCondition` returns false) — including
applications first seen with a populated detail, already-posted applications re-scraped with no
meaningful change, genuinely new populated applications, and all non-FCC-ELS content — the fixed
system SHALL produce the same observable result as the original system: the same posting decision,
the same rendered header fields, the same "Открыть заявку" link, and the same behavior for NOTAMs,
FAA activities, beach alerts, and road alerts.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct, the fix defers posting until an application's detail
is populated. The recommended point of change is post-eligibility (cause #3), which is the smallest
change with the least regression surface and does not alter how records are persisted.

**File**: `starship_notam/data/fcc_els_repo.py`

**Function**: `get_fcc_els_applications_needing_post`

**Specific Changes**:
1. **Gate post-eligibility on non-empty detail**: In addition to `telegram_posted = 0`, require
   that the row's `detail_json` represents a non-empty detail. In SQL terms, exclude rows where
   `detail_json IS NULL OR TRIM(detail_json) = '' OR TRIM(detail_json) = '{}'`, keeping the
   existing `telegram_posted = 0` and `ORDER BY created_at` clauses intact.
   - This ensures an application with an empty detail is never returned for posting, so it is
     never posted incomplete, deferring the post until the detail populates.
   - A single source of truth for the "empty detail" test avoids drift; consider a small helper
     (e.g. `_is_empty_detail_json(value)`) mirroring the SQL predicate for use in tests.

2. **Preserve the reset-to-zero mechanism**: Do NOT change `save_fcc_els_application`. The
   empty→populated transition still bumps `payload_hash` and resets `telegram_posted = 0`; because
   the empty-detail row was never posted, the now-populated row is simply posted once. This keeps
   the genuine "content changed, re-post" behavior intact for other legitimate detail changes.

**File**: `starship_notam/bot/orchestrator.py`

**Function**: `_process_fcc_els_applications`

**Specific Changes**:
3. **No behavioral change required if the query is the gate**: Because posting is driven entirely
   by `get_fcc_els_applications_needing_post`, gating at the query level automatically defers
   empty-detail applications with no orchestrator edit. If, alternatively, the gate is implemented
   in the orchestrator (defense in depth), add a guard that skips posting any `app` whose
   `detail_json` is empty (leaving `telegram_posted = 0` so it is retried once populated) and logs
   the deferral at INFO. Prefer a single gate to avoid divergent definitions of "empty".

**Optional hardening (not required to fix the bug)**:
4. **Scraper-level discard of empty detail**: `fetch_fcc_els_applications` could skip appending an
   application whose parsed `detail == {}` (treating an empty parse like a failed one). This would
   prevent empty-detail rows from being persisted at all. This is left optional because it changes
   persistence behavior (rows would no longer be recorded until detail is available) and is not
   necessary once posting is gated; if adopted it must preserve Requirement 3.1/3.3 (populated
   applications still saved and posted).

The recommended, minimal implementation is change #1 (query gate) plus #2 (leave save untouched).

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate
the bug on the UNFIXED code (an application posted while its detail is empty, then re-posted once
populated), then verify the fix posts exactly once with complete detail and preserves all other
behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm or
refute the root cause analysis (empty-detail rows are post-eligible and the empty→populated
transition re-posts). If refuted, re-hypothesize.

**Test Plan**: Using an in-memory / temp SQLite DB, drive the persistence + post-eligibility path
directly: save an application with `detail == {}`, observe it is returned by
`get_fcc_els_applications_needing_post` and rendered without the purpose/explanation; then save the
same `file_number` with a populated detail and observe `telegram_posted` reset to 0 and the row
returned again. Run these against the UNFIXED code to observe the double eligibility.

**Test Cases**:
1. **Empty-detail is post-eligible**: Save an app with `detail == {}`; assert it appears in
   `get_fcc_els_applications_needing_post` (will be true on unfixed code — demonstrates the
   incomplete post).
2. **Empty→populated re-eligibility**: Save empty, mark posted, then save populated for the same
   `file_number`; assert `telegram_posted` resets to 0 and the row is returned again (will be true
   on unfixed code — demonstrates the duplicate).
3. **Rendered message omits detail fields**: Format the empty-detail app via
   `format_fcc_els_application`; assert the output lacks "Цель эксплуатации" and "Обоснование"
   (true on unfixed code — this is the incomplete message).
4. **Edge case — detail stays empty**: Save empty twice (no change); assert no second update/post
   is triggered by the no-change branch (characterizes current behavior around the boundary).

**Expected Counterexamples**:
- The empty-detail application is post-eligible and its message omits the purpose/explanation.
- After populating, the same `file_number` becomes post-eligible again (duplicate).
- Possible causes: query ignores detail completeness; `detail_json` participates in `payload_hash`
  and resets `telegram_posted`.

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed function produces the
expected behavior (a single, complete post per `file_number`).

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  // input: application seen empty first, then populated
  applyScrapeSequence(F', input)          // save empty, then save populated
  posts := telegramPostsFor(F', input.file_number)
  ASSERT count(posts) = 1
     AND detailFieldsPresent(posts[0])    // "Цель эксплуатации" AND "Обоснование"
END FOR
```

Concretely: the empty-detail save is deferred (not returned by the eligibility query), so no post
occurs; the populated save is returned exactly once and, when formatted, includes both detail
fields.

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed system
produces the same result as the original system.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT observableBehavior(F, input) = observableBehavior(F', input)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many application shapes (varied header fields, populated details, prior-posted
  states) across the input domain automatically.
- It catches edge cases manual unit tests might miss (e.g. whitespace-only `detail_json`,
  duplicate labels).
- It provides strong guarantees that behavior is unchanged for all non-buggy inputs.

**Test Plan**: Observe behavior on UNFIXED code first for populated-first applications, no-change
re-scrapes, and non-FCC-ELS content, then write tests (property-based where practical) capturing
that behavior and asserting the fixed code matches.

**Test Cases**:
1. **Populated-first still posts once**: Save an app with a populated detail on first appearance;
   assert it is post-eligible and its formatted message includes the detail fields (matches
   unfixed behavior — 3.1).
2. **No-change re-scrape not re-posted**: Save a populated app, mark posted, save identical payload
   again; assert `telegram_posted` stays 1 and no DB update occurs (matches unfixed behavior — 3.2).
3. **New populated application posts**: Save a new `file_number` with populated detail; assert it
   is post-eligible (matches unfixed behavior — 3.3).
4. **Header fields and link preserved**: Assert `format_fcc_els_application` still renders
   Заявитель, Номер дела, Позывной, Статус, Дата получения, Дата статуса and the "Открыть заявку"
   link identically to today (3.4).
5. **Other content types unaffected**: Assert NOTAM, FAA, beach, and road eligibility/formatting
   paths are unchanged (3.5); these do not touch the modified query.

### Unit Tests

- `get_fcc_els_applications_needing_post` excludes rows whose `detail_json` is `NULL`, `''`, or
  `'{}'`, and includes rows with populated `detail_json` and `telegram_posted = 0`.
- Empty-detail application is not post-eligible; populated application is.
- Empty→populated transition results in a single eligible (post-once) row.
- `format_fcc_els_application` renders detail fields for populated detail and omits them for empty
  detail (characterization).
- Header fields and "Открыть заявку" link render as before.

### Property-Based Tests

- Generate random applications with populated details and assert post-eligibility and complete
  rendering are unchanged by the fix (preservation).
- Generate random empty-detail representations (`{}`, `''`, whitespace, `NULL`) and assert none are
  post-eligible (fix).
- Generate empty→populated scrape sequences and assert exactly one post per `file_number` with the
  detail fields present (fix).

### Integration Tests

- Full FCC ELS flow: scrape sequence (empty then populated) through
  `_process_fcc_els_applications` results in a single complete Telegram message per `file_number`.
- Context/mixed run: an FCC ELS empty-detail deferral in the same cycle as NOTAM/FAA/beach/road
  processing does not disturb those pipelines.
- Verify the deferred application is eventually posted once its detail populates on a later cycle.
