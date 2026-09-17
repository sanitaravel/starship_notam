# Implementation Plan: FCC ELS Scraper

## Overview

This plan implements a new FCC Experimental Licensing System (ELS) data source in
the existing `starship_notam` Python application, mirroring the established FAA
activity pipeline across five layers (`parsers` → `scrapers` → `data` → `bot`
formatter → `bot` orchestrator). The plan is test-driven and incremental: pure
and leaf units (parser, date helpers, formatter, schema + repository) are built
and unit-tested first, then the Selenium scraper, then orchestrator wiring, then
package exports, and finally the structural boundary / import-isolation
verification.

Language: Python 3.12 (the design specifies concrete Python throughout; no
language selection is required). Testing uses pytest with the existing
`db_path` / `initialized_db` fixtures and `asyncio_mode=auto`. Property tests
use Hypothesis (`@settings(max_examples=100)`) and are tagged
`# Feature: fcc-els-scraper, Property N: <text>`.

## Tasks

- [x] 1. Add test tooling and optional config constants
  - [x] 1.1 Add Hypothesis to the dev dependencies
    - In `pyproject.toml`, add `hypothesis` (pinned) to
      `[project.optional-dependencies].dev` alongside `pytest` and
      `pytest-asyncio`
    - This enables the property-based tests written in later tasks
    - _Requirements: 9.7_

  - [ ] 1.2 Add FCC ELS config constants
    - In `starship_notam/core/config.py`, add module-level constants
      `FCC_ELS_SEARCH_URL` (`https://apps.fcc.gov/oetcf/els/reports/GenericSearch.cfm`),
      `FCC_ELS_SEARCH_TERM` (`"Space Exploration"`), and
      `FCC_ELS_RECORD_LIMIT` (`50`)
    - Keep imports stdlib-only, matching the existing `core` layer conventions
    - _Requirements: 1.3, 1.6, 9.2_

- [x] 2. Implement the ELS_Parser pure functions
  - [x] 2.1 Create `parsers/fcc_els_parser.py` with `parse_fcc_els_results_html`
    - Module-level imports only: `from __future__ import annotations`, `re`,
      `from urllib.parse import urlparse, parse_qs`,
      `from bs4 import BeautifulSoup`, and
      `from starship_notam.core.logging import logger` (no `data` /
      `visualization` imports)
    - Locate the results table via a header-label → column-index map (resilient
      to column reordering); iterate data `<tr>` rows
    - Extract `file_number`, `call_sign`, `applicant_name`, `receipt_date`,
      `status`, `status_date`, trimming each with `.strip()`
    - Normalize `call_sign` to `""` when blank/all-whitespace/"N/A"
      (case-insensitive)
    - Find the "View Form → Current" link (href contains `STA_Print.cfm` and
      `mode=current`), set `current_detail_url`, and extract `application_seq`
      via `parse_qs(urlparse(href).query).get("application_seq", [None])[0]`
    - Exclude and log rows missing `file_number`, `current_detail_url`, or
      `application_seq`; return `[]` when there are no data rows
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 4.7, 9.2_

  - [x] 2.2 Implement `parse_fcc_els_detail_html` in the same module
    - Parse STA_Print label/value pairs: for each `<tr>` with two or more
      `<td>`/`<th>` cells, treat the first non-empty cell as label and the next
      non-empty cell as value, trimming both and stripping a trailing colon
      from the label
    - Skip section-header rows (single spanning cell) and empty-value rows;
      duplicate labels keep the last occurrence
    - Return `{label: value}`; return `{}` when no pairs are recognized
    - _Requirements: 3.4, 3.5, 4.7, 9.2_

  - [x] 2.3 Write property tests for the results parser
    - Create `tests/unit/test_parsers/test_fcc_els_parser.py`; Hypothesis
      strategies generate results-table HTML from field-value records with
      random whitespace, random call-sign blanks/"N/A", random extra query
      params/ordering on Current links, and interleaved invalid rows
    - **Property 1: One result dict per valid row** — _Validates: Requirements 2.1, 2.2_
    - **Property 2: Valid rows round-trip their field values** — _Validates: Requirements 2.3, 2.5, 2.6_
    - **Property 3: Call-sign normalization** — _Validates: Requirements 2.4_
    - **Property 4: Exclusion invariant for incomplete rows** — _Validates: Requirements 2.7_
    - _Properties: 1, 2, 3, 4_
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [x] 2.4 Write property + edge-case tests for the detail parser
    - In `tests/unit/test_parsers/test_fcc_els_parser.py`, generate STA_Print
      detail HTML from random label/value pair sets, including the empty /
      no-field case
    - **Property 5: Detail label/value extraction** — _Validates: Requirements 3.4, 3.5_
    - Add example tests: empty/no-rows results HTML → `[]` (Req 2.8);
      unrecognized detail HTML → `{}` (Req 3.5)
    - _Properties: 5_
    - _Requirements: 2.8, 3.4, 3.5_

- [x] 3. Create the FCC ELS database schema
  - [x] 3.1 Add the `fcc_els_applications` table to `connection.init_db`
    - In `starship_notam/data/connection.py`, append a `CREATE TABLE IF NOT
      EXISTS fcc_els_applications (...)` block with columns: `id` PK
      AUTOINCREMENT, `file_number TEXT UNIQUE NOT NULL`, `application_seq`,
      `applicant_name`, `call_sign`, `receipt_date`, `status`, `status_date`,
      `current_detail_url`, `detail_json`, `created_at TEXT NOT NULL`,
      `updated_at TEXT NOT NULL`, `payload_hash`, `telegram_posted INTEGER
      DEFAULT 0`, `telegram_posted_at`, `telegram_message_id`
    - Add an additive `PRAGMA table_info(fcc_els_applications)` migration that
      `ALTER TABLE ... ADD COLUMN` for any missing column without dropping or
      recreating the table
    - Place the block inside the existing outer `try/except` that rolls back and
      re-raises on error; follow the per-table `commit()` pattern
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [x] 3.2 Write schema tests
    - In `tests/unit/test_data`, add tests using the `db_path` fixture:
      `init_db` on a fresh DB creates the table with the expected columns and
      the `file_number` UNIQUE constraint (Req 6.1, 6.3, 6.4); running `init_db`
      twice preserves an inserted row (Req 6.2); a pre-created partial table
      gains missing columns additively without losing rows (Req 6.5)
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

- [ ] 4. Implement the ELS_Repository
  - [x] 4.1 Create `data/fcc_els_repo.py` with `save_fcc_els_application`
    - Module-level imports only: `hashlib`, `json`, `typing`,
      `from starship_notam.core.logging import logger`, and
      `from starship_notam.data.connection import get_connection, init_db,
      utc_now_iso` (no third-party imports)
    - Call `init_db(db_path)`, serialize `detail_json = json.dumps(app.get(
      "detail") or {}, sort_keys=True, ensure_ascii=False)`, and compute
      `payload_hash` as SHA-256 over the full payload with `json.dumps(...,
      sort_keys=True)`
    - SELECT existing `payload_hash` by `file_number`: no row → INSERT with
      `created_at = updated_at = utc_now_iso()`, `telegram_posted = 0`; hash
      equal → return unchanged; hash differs → UPDATE fields + `detail_json`,
      refresh `updated_at`, store new hash, reset `telegram_posted = 0`
    - `commit()` on success; on exception `rollback()` then re-raise; `close()`
      in `finally`
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.7, 9.3_

  - [x] 4.2 Implement the query and mark functions in the same module
    - `get_fcc_els_applications_needing_post(db_path=None)` selects the full row
      set with `telegram_posted = 0` ordered by `created_at`, returning
      `dict(row)` per row (including `detail_json`)
    - `mark_fcc_els_application_posted(file_number, telegram_message_id,
      db_path=None)` sets `telegram_posted = 1`, `telegram_posted_at =
      utc_now_iso()`, and `telegram_message_id` WHERE `file_number = ?`
    - _Requirements: 5.6, 7.1, 9.3_

  - [x] 4.3 Write property tests for the repository
    - Create `tests/unit/test_data/test_fcc_els_repo.py` using a `tmp_path`
      `db_path` (matching existing repo tests)
    - **Property 8: Payload hash is key-order independent** — _Validates: Requirements 5.2_
    - **Property 9: Re-saving an unchanged application never re-flags it** — _Validates: Requirements 5.4_
    - **Property 10: A changed application is re-flagged for posting** — _Validates: Requirements 5.5_
    - **Property 11: File number uniqueness** — _Validates: Requirements 5.1, 6.4_
    - **Property 12: Needing-post query returns exactly the unposted set** — _Validates: Requirements 7.1_
    - _Properties: 8, 9, 10, 11, 12_
    - _Requirements: 5.1, 5.2, 5.4, 5.5, 6.4, 7.1_

  - [x] 4.4 Write repository example tests
    - Insert sets `telegram_posted = 0` with timestamps and hash (Req 5.3);
      `mark_*_posted` populates the three Telegram columns (Req 5.6); a forced
      DB error causes rollback + raise with no partial row (Req 5.7)
    - _Requirements: 5.3, 5.6, 5.7_

- [ ] 5. Checkpoint - Ensure all pure-layer tests pass
  - Ensure all parser, schema, and repository tests pass; ask the user if
    questions arise.

- [x] 6. Implement the ELS_Formatter
  - [x] 6.1 Add `format_fcc_els_application` to `bot/formatting.py`
    - Stdlib only (`html`, `json`); build a Russian-language HTML string with a
      `"<b>Новая заявка FCC ELS</b>"` header and `<b>`-labelled lines for
      applicant, file number, call sign (only when non-empty), status, receipt
      date, and status date
    - Parse `detail_json` (accept a dict or a JSON string, like
      `format_beach_alert` handles `periods_json`) and render the full raw
      detail field set inside an expandable `<blockquote expandable>`, each line
      `f"{html.escape(label)}: {html.escape(value)}"`
    - Pass all user-supplied text through `html.escape`; join with `"\n\n"`; no
      network I/O
    - _Requirements: 7.3, 7.9, 9.4_

  - [x] 6.2 Write property test for the formatter
    - Create `tests/unit/test_bot/test_fcc_els_formatting.py`; generate
      application dicts whose field values include `<`, `>`, `&`
    - **Property 13: Formatter output is well-formed and escaped** — _Validates: Requirements 7.3_
    - _Properties: 13_
    - _Requirements: 7.3_

- [ ] 7. Implement the ELS_Scraper
  - [x] 7.1 Create date helpers in `scrapers/fcc_els_fetcher.py`
    - Add pure helpers `_receipt_date_to(today=None)` (today as `mm/dd/yyyy`)
      and `_receipt_date_from(today=None)` (today − 1 calendar month, wrapping
      year and clamping the day to the target month's last valid day, formatted
      `%m/%d/%Y`), defaulting `today` to `date.today()`
    - Module-level imports: `os`, `time`, `datetime`/`date`,
      `starship_notam.core.logging.logger`, `starship_notam.core.config`, and
      `from starship_notam.parsers.fcc_els_parser import
      parse_fcc_els_results_html, parse_fcc_els_detail_html` (no module-level
      Selenium)
    - Add `DEBUG_MODE = os.environ.get("DEBUG_MODE") == "1"` at module level
    - _Requirements: 1.4, 1.5, 9.1_

  - [ ]* 7.2 Write property test for the date helpers
    - Create `tests/unit/test_scrapers/__init__.py` (or `.gitkeep`) and
      `tests/unit/test_scrapers/test_fcc_els_dates.py`; use
      `hypothesis.strategies.dates()`
    - **Property 7: Receipt-date helpers are correct for all dates** — _Validates: Requirements 1.4, 1.5_
    - _Properties: 7_
    - _Requirements: 1.4, 1.5_

  - [x] 7.3 Implement `fetch_fcc_els_applications`
    - Lazily import Selenium inside the function (`webdriver`, `Remote`, `By`,
      `WebDriverWait`, `expected_conditions as EC`); build headless
      `ChromeOptions` with the same flags as the NOTAM scraper
    - Choose `webdriver.Chrome` when `DEBUG_MODE` else
      `Remote("http://selenium:4444/wd/hub", options=options)`
    - In a `try/finally` with `driver.quit()` in `finally`: `get`
      `config.FCC_ELS_SEARCH_URL`; `WebDriverWait(driver, 30)` for the four
      fields, returning `[]` on timeout; fill licensee =
      `config.FCC_ELS_SEARCH_TERM`, receipt-from = `_receipt_date_from()`,
      receipt-to = `_receipt_date_to()`, show-records =
      `config.FCC_ELS_RECORD_LIMIT`; submit; `WebDriverWait(driver, 30)` for the
      results table, returning `[]` on timeout
    - `rows = parse_fcc_els_results_html(driver.page_source)`; return `[]` and
      raise nothing on any search/navigation failure
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 4.2, 4.3, 4.4, 4.5, 4.6, 9.1_

  - [x] 7.4 Implement per-row detail retrieval and merge
    - For each row, retry `driver.get(row["current_detail_url"])` up to 3 times
      with a 30-second `page_load_timeout`; on success `detail =
      parse_fcc_els_detail_html(driver.page_source)`
    - Build the application dict merging identity + row fields + `detail`
      (`file_number`, `application_seq`, `applicant_name`, `call_sign`,
      `receipt_date`, `status`, `status_date`, `current_detail_url`, `detail`)
    - On per-row failure: log the failing `file_number` and cause, discard the
      partial data, and continue; return the accumulated list
    - _Requirements: 3.1, 3.2, 3.3, 3.6, 3.7, 4.1_

  - [ ]* 7.5 Write scraper example tests with a mocked Selenium driver
    - Create `tests/unit/test_scrapers/test_fcc_els_fetcher.py`: licensee filled
      with "Space Exploration" (Req 1.3); show-records set to 50 (Req 1.6);
      submit after fields populated (Req 1.7); parser called with `page_source`
      (Req 3.3, 4.2); retry succeeds on the 3rd attempt and a 4th failure is
      treated as failed (Req 3.2); one failing row does not drop the others
      (Req 3.7); `[]` and no raise on setup/search/nav failure (Req 1.2, 1.9,
      4.4); `driver.quit()` on both success and error paths (Req 4.5, 4.6)
    - **Property 6: Merged application preserves identity** — _Validates: Requirements 3.6, 4.1_
    - _Properties: 6_
    - _Requirements: 1.2, 1.3, 1.6, 1.7, 1.9, 3.2, 3.3, 3.6, 3.7, 4.1, 4.2, 4.4, 4.5, 4.6_

- [ ] 8. Wire the new units into package exports
  - [x] 8.1 Export the scraper function from `scrapers/__init__.py`
    - Add `from .fcc_els_fetcher import fetch_fcc_els_applications` and append
      `"fetch_fcc_els_applications"` to `__all__`, matching the existing export
      pattern
    - _Requirements: 9.5_

  - [x] 8.2 Export the repository functions from `data/__init__.py`
    - Add imports for `save_fcc_els_application`,
      `get_fcc_els_applications_needing_post`, and
      `mark_fcc_els_application_posted`, and append the three names to `__all__`
    - _Requirements: 9.5_

- [ ] 9. Integrate into the orchestrator
  - [x] 9.1 Add `_process_fcc_els_applications` to `bot/orchestrator.py`
    - Add module-level imports for the three repo functions from
      `starship_notam.data`, `fetch_fcc_els_applications` from
      `starship_notam.scrapers`, and `format_fcc_els_application` from
      `starship_notam.bot.formatting`
    - Implement `async def _process_fcc_els_applications(chat_list)` mirroring
      `_process_faa_activities`: `apps = await asyncio.to_thread(
      fetch_fcc_els_applications)` in `try/except`; save each app in its own
      `try/except` via `save_fcc_els_application(app, config.DB_PATH)`; query
      `get_fcc_els_applications_needing_post(config.DB_PATH)` and return early
      if empty
    - For each pending app: `format_fcc_els_application(app)`, send to each chat
      via `send_message` collecting successful ids with `await
      asyncio.sleep(5)` between chats; a `None`/failed send is logged and does
      not count; mark posted via `mark_fcc_els_application_posted(app[
      "file_number"], ",".join(ids), config.DB_PATH)` only when at least one
      send succeeds; wrap every per-app step in `try/except`
    - _Requirements: 7.2, 7.4, 7.5, 7.6, 7.7, 7.8, 8.2, 8.3, 8.4, 8.5, 8.6, 9.6_

  - [x] 9.2 Call the new step from `generate_and_send`
    - Invoke `await _process_fcc_els_applications(chat_list)` immediately after
      `await _process_faa_activities(chat_list)` in `generate_and_send`
    - _Requirements: 8.1, 5.8_

  - [ ]* 9.3 Write orchestrator example tests
    - Add tests (mocked scraper/repo/transport, patched `asyncio.to_thread` and
      `asyncio.sleep`) in `tests/unit/test_bot`: the step runs
      fetch→persist→post (Req 8.1); scraper runs via `asyncio.to_thread`
      (Req 8.2); a 5-second pause between chats (Req 7.4); marking uses returned
      message ids (Req 7.5); one chat failing still attempts others (Req 7.6);
      all sends failing leaves the app unposted (Req 7.7); no pending apps → no
      send (Req 7.8); fetch/persist/send/step failures are logged and the cycle
      continues (Req 8.3–8.6)
    - _Requirements: 7.4, 7.5, 7.6, 7.7, 7.8, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

- [ ] 10. Verify structural boundaries and import isolation
  - [ ] 10.1 Confirm dependency-boundary and import-isolation suites pass
    - Run `tests/integration/test_dependency_boundaries.py` and
      `tests/integration/test_import_isolation.py`; the new modules
      (`fcc_els_parser`, `fcc_els_fetcher`, `fcc_els_repo`, formatter) MUST pass
      with NO new allow-list entries; fix any module-level import that violates
      the layer rules (e.g. Selenium must stay lazy)
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.6, 9.7_

  - [ ]* 10.2 Add export-availability tests
    - Assert `starship_notam.scrapers.fetch_fcc_els_applications` and the three
      `starship_notam.data` repo functions are importable and listed in each
      package's `__all__`
    - _Requirements: 9.5_

- [ ] 11. Final checkpoint - Run the full suite and verify the build
  - Run the full `pytest` suite (including the new property tests) plus the
    dependency-boundary and import-isolation tests, and verify the application
    still imports (e.g. `python -c "import starship_notam"`). Ensure all tests
    pass; ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a
  faster MVP; core implementation tasks are never optional.
- Each task references specific requirements for traceability, and property-test
  tasks reference their design correctness property via `_Properties: N_`.
- Property tests use Hypothesis with `@settings(max_examples=100)` and are
  tagged `# Feature: fcc-els-scraper, Property N: <text>`.
- Checkpoints ensure incremental validation at natural layer boundaries.
- No new dependency-boundary allow-list entries should be required; Selenium is
  imported lazily inside `fetch_fcc_els_applications`.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "2.1", "3.1", "6.1"] },
    { "id": 1, "tasks": ["2.2", "2.3", "3.2", "4.1", "6.2", "7.1"] },
    { "id": 2, "tasks": ["2.4", "4.2", "7.2", "7.3", "8.1"] },
    { "id": 3, "tasks": ["4.3", "7.4", "8.2"] },
    { "id": 4, "tasks": ["4.4", "7.5", "9.1"] },
    { "id": 5, "tasks": ["9.2", "10.2"] },
    { "id": 6, "tasks": ["9.3", "10.1"] }
  ]
}
```
