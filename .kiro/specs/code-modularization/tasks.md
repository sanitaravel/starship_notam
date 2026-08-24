# Implementation Plan: Code Modularization

## Overview

Refactor the Starship NOTAM monitoring and Telegram bot project from a flat file structure into a well-organized package-based architecture. The implementation proceeds layer by layer starting with the core package (no dependencies), then leaf packages (parsers, data), then I/O packages (scrapers, visualization), then the bot layer, and finally wiring everything together with backward-compatible re-exports and entry points.

## Tasks

- [x] 1. Create core package with configuration and logging
  - [x] 1.1 Create the `starship_notam/core/` package with `__init__.py`, `config.py`, and `logging.py`
    - Create directory `starship_notam/core/`
    - Create `starship_notam/core/__init__.py` that re-exports `config` and `logging` module contents
    - Create `starship_notam/core/config.py` that loads environment variables using `python-dotenv` and exposes typed constants: `TELEGRAM_BOT_TOKEN` (str, required — raises `RuntimeError` if missing), `CHAT_IDS` (list[str] parsed from comma-separated env var), `DB_PATH` (str, default `"notams.db"`), `KEYWORD` (str, default `"STARSHIP"`), `RUNS_PER_HOUR` (int, default `2`), `STATE_PATH` (str, path to `telegram_chats.json`)
    - Create `starship_notam/core/logging.py` that configures a `logger` instance with `RichHandler` (console) and `RotatingFileHandler` (writing to `logs/notam.log`), and exposes a shared `rich.console.Console` instance
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

- [x] 2. Create parsers package (pure functions, no I/O)
  - [x] 2.1 Create `starship_notam/parsers/` package with `__init__.py` and `notam_parser.py`
    - Create directory `starship_notam/parsers/`
    - Create `starship_notam/parsers/__init__.py` re-exporting public parser functions
    - Extract NOTAM text parsing logic (ICAO fields, CARF messages, Q-line parsing) from `notam_parser.py` into `starship_notam/parsers/notam_parser.py`
    - Functions: `parse_notam(text: str) -> dict`, `parse_carf_message(text: str) -> dict`
    - Ensure no database, network, or filesystem imports remain
    - _Requirements: 3.1, 3.5, 3.6_

  - [x] 2.2 Create `starship_notam/parsers/coord_parser.py`
    - Extract coordinate parsing logic (DMS, decimal, polygon extraction) from `visualize_notams.py` into `starship_notam/parsers/coord_parser.py`
    - Function: `parse_coords_from_text(raw: str) -> list[tuple[float, float]] | tuple[float, float] | None`
    - Ensure the module only uses standard library modules (`re`, `typing`)
    - _Requirements: 3.2, 3.5, 3.6_

  - [x] 2.3 Create `starship_notam/parsers/faa_parser.py`
    - Extract FAA advisory HTML parsing logic from `fetch_faa_advisory.py` into `starship_notam/parsers/faa_parser.py`
    - Function: `parse_faa_advisory_html(html: str) -> list[dict]` returning list of `{"mission": ..., "primary_window": ..., "backup_window": ...}`
    - Only allowed imports: standard library + `beautifulsoup4`
    - _Requirements: 3.3, 3.5, 3.6_

  - [x] 2.4 Create `starship_notam/parsers/starbase_parser.py`
    - Extract Starbase closure HTML parsing logic from `fetch_starbase_closures.py` into `starship_notam/parsers/starbase_parser.py`
    - Function: `parse_starbase_html(html: str) -> dict` returning `{"beach": {...} | None, "road_delays": [...]}`
    - Only allowed imports: standard library + `beautifulsoup4`
    - _Requirements: 3.4, 3.5, 3.6_

- [ ] 3. Create data package (database layer)
  - [ ] 3.1 Create `starship_notam/data/` package with `__init__.py` and `connection.py`
    - Create directory `starship_notam/data/`
    - Create `starship_notam/data/__init__.py` re-exporting public data functions
    - Create `starship_notam/data/connection.py` with `get_connection(db_path: str | None = None) -> sqlite3.Connection` and `init_db(db_path: str | None = None) -> None`
    - Extract SQLite connection management and schema creation/migration logic from `notam_db.py`
    - Use `core.config.DB_PATH` as default when `db_path` is None; also check `NOTAM_DB_PATH` environment variable
    - Ensure transactions are rolled back on failure
    - _Requirements: 2.1, 2.4, 2.5_

  - [ ] 3.2 Create `starship_notam/data/notam_repo.py`
    - Extract NOTAM persistence functions from `notam_db.py` into `starship_notam/data/notam_repo.py`
    - Functions: `save_notam(name, parsed, db_path=None)`, `get_notams_needing_images(db_path=None)`, `mark_image_generated(name, db_path=None)`, `load_all_notams(db_path=None)`
    - Functions accept and return plain Python dictionaries
    - Import only from `data.connection`, `core`, and Python standard library
    - _Requirements: 2.2, 2.3, 2.5, 2.6_

  - [ ] 3.3 Create `starship_notam/data/faa_repo.py`
    - Extract FAA activity persistence functions from `notam_db.py` into `starship_notam/data/faa_repo.py`
    - Functions: `save_faa_activity(activity, db_path=None)`, `get_faa_activities_needing_post(db_path=None)`, `mark_faa_activity_posted(mission, telegram_message_id, db_path=None)`
    - Import only from `data.connection`, `core`, and Python standard library
    - _Requirements: 2.2, 2.3, 2.5, 2.6_

  - [ ] 3.4 Create `starship_notam/data/starbase_repo.py`
    - Extract Starbase alert persistence functions from `notam_db.py` into `starship_notam/data/starbase_repo.py`
    - Functions: `save_beach_alert(alert, db_path=None)`, `save_road_alert(alert, db_path=None)`, `get_beach_alerts_needing_post(db_path=None)`, `get_road_alerts_needing_post(db_path=None)`, `mark_beach_posted(alert_key, db_path=None)`, `mark_road_posted(alert_key, db_path=None)`
    - Import only from `data.connection`, `core`, and Python standard library
    - _Requirements: 2.2, 2.3, 2.5, 2.6_

- [ ] 4. Create scrapers package (I/O layer)
  - [ ] 4.1 Create `starship_notam/scrapers/` package with `__init__.py` and `notam_scraper.py`
    - Create directory `starship_notam/scrapers/`
    - Create `starship_notam/scrapers/__init__.py` re-exporting public scraper functions
    - Extract Selenium-based NOTAM search from `notam_request.py` into `starship_notam/scrapers/notam_scraper.py`
    - Function: `search_notams(keyword: str) -> list[dict]` — returns list of result dicts with keys: `location`, `number`, `class`, `start_date_utc`, `end_date_utc`, `condition`, `icao_message`
    - Use lazy import for `selenium` (import inside function body)
    - Does NOT persist to database; raises exception or returns empty list on failure
    - _Requirements: 4.1, 4.3, 4.4, 4.6_

  - [ ] 4.2 Create `starship_notam/scrapers/faa_fetcher.py`
    - Extract HTTP-based FAA advisory fetching from `fetch_faa_advisory.py` into `starship_notam/scrapers/faa_fetcher.py`
    - Function: `fetch_faa_advisory() -> list[dict]` — performs HTTP GET, passes HTML to `parsers.faa_parser.parse_faa_advisory_html`, returns parsed list
    - Returns list of dicts with keys: `mission`, `primary_window`, `backup_window`
    - Does NOT persist to database; raises exception or returns empty list on failure
    - _Requirements: 4.2, 4.3, 4.5, 4.6_

  - [ ] 4.3 Create `starship_notam/scrapers/starbase_fetcher.py`
    - Extract HTTP-based Starbase status fetching from `fetch_starbase_closures.py` into `starship_notam/scrapers/starbase_fetcher.py`
    - Function: `fetch_starbase_status() -> dict` — performs HTTP GET, passes HTML to `parsers.starbase_parser.parse_starbase_html`, returns parsed dict
    - Does NOT persist to database; raises exception or returns empty list on failure
    - _Requirements: 4.2, 4.3, 4.6_

- [ ] 5. Create visualization package
  - [ ] 5.1 Create `starship_notam/visualization/` package with `__init__.py` and `map_renderer.py`
    - Create directory `starship_notam/visualization/`
    - Create `starship_notam/visualization/__init__.py` re-exporting `render_notam_image`
    - Extract Cartopy/Matplotlib map rendering logic from `visualize_notams.py` into `starship_notam/visualization/map_renderer.py`
    - Function: `render_map(coords, size: tuple[int, int], radius_nm: float | None = None) -> PIL.Image.Image`
    - Use lazy import for `cartopy` and `matplotlib` (import inside function body)
    - Raise `ImportError` with clear message if Cartopy/Matplotlib is missing
    - _Requirements: 6.2, 6.6, 6.7_

  - [ ] 5.2 Create `starship_notam/visualization/image_composer.py`
    - Extract PIL-based image composition logic from `visualize_notams.py` into `starship_notam/visualization/image_composer.py`
    - Function: `render_notam_image(notam_dict: dict, output_path: str) -> str` and `plot_single_notam(name, parsed, coords, out_path, _unused=None) -> str`
    - Import `parse_coords_from_text` from `starship_notam.parsers.coord_parser` for coordinate extraction
    - Import `render_map` from `starship_notam.visualization.map_renderer` for map tile
    - Fall back to default global map extent if coordinates are missing or unparseable
    - _Requirements: 6.1, 6.3, 6.4, 6.5, 6.7_

- [ ] 6. Checkpoint - Verify leaf packages
  - Ensure all leaf packages (core, parsers, data, scrapers, visualization) are importable independently.
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Create bot package
  - [ ] 7.1 Create `starship_notam/bot/` package with `__init__.py` and `formatting.py`
    - Create directory `starship_notam/bot/`
    - Create `starship_notam/bot/__init__.py` re-exporting public bot functions
    - Extract message formatting functions from `telegram_bot.py` into `starship_notam/bot/formatting.py`
    - Functions: `build_notam_caption(name, parsed) -> str`, `format_faa_activity(activity) -> str`, `format_road_alert(alert) -> str`, `format_beach_alert(alert) -> str`
    - This module must NOT import Telegram API or perform network I/O
    - _Requirements: 5.1, 5.4_

  - [ ] 7.2 Create `starship_notam/bot/transport.py`
    - Extract Telegram API interaction from `telegram_bot.py` into `starship_notam/bot/transport.py`
    - Functions: `async send_photo(chat_id, photo_path, caption=None) -> bool`, `async send_message(chat_id, text) -> int | None`, `async refresh_known_chats() -> list[str]`
    - Use lazy import for `telegram` (python-telegram-bot) inside function body
    - Import config from `core.config` for bot token
    - This module must NOT import formatting or data-fetching modules
    - Return `None`/`False` on send failures; remove blocked chats (403) from state
    - _Requirements: 5.2, 5.4, 5.5_

  - [ ] 7.3 Create `starship_notam/bot/orchestrator.py`
    - Extract main orchestration loop and scheduling logic from `telegram_bot.py` into `starship_notam/bot/orchestrator.py`
    - Functions: `async main_loop() -> None`, `async generate_and_send(chat_list=None) -> None`
    - Import from `bot.formatting`, `bot.transport`, `scrapers.*`, `data.*`, `visualization.*`, and `core.config`
    - Wrap each processing step in try/except, log exceptions, continue to next step
    - The main loop must never terminate due to a transient error
    - _Requirements: 5.3, 5.4, 8.2_

- [ ] 8. Create top-level package init and entry point
  - [ ] 8.1 Create `starship_notam/__init__.py` with backward-compatible re-exports
    - Create `starship_notam/__init__.py` that re-exports every public function and object previously importable from flat modules
    - Map: `notam_db` → `data`, `notam_parser` → `parsers`, `notam_request` → `scrapers`, `notam_logging` → `core`, `telegram_bot` → `bot`, `visualize_notams` → `visualization`, `fetch_faa_advisory` → `scrapers`, `fetch_starbase_closures` → `scrapers`
    - Use lazy imports where possible to avoid loading heavy dependencies at package import time
    - _Requirements: 1.3, 1.4, 8.3_

  - [ ] 8.2 Create `starship_notam/__main__.py` entry point
    - Create `starship_notam/__main__.py` that imports and runs `bot.orchestrator.main_loop()`
    - Initialize database via `data.connection.init_db()`
    - Refresh Telegram chats via `bot.transport.refresh_known_chats()`
    - Enter the scheduled monitoring loop
    - Supports invocation via `python -m starship_notam`
    - _Requirements: 8.1, 8.2_

  - [ ] 8.3 Create top-level `main.py` convenience script
    - Create `main.py` at project root that invokes `starship_notam.__main__` logic
    - Provides the same behavior as the current `python telegram_bot.py` invocation
    - _Requirements: 8.1, 8.2_

- [ ] 9. Checkpoint - Verify full application startup
  - Ensure the application starts correctly via `python -m starship_notam` and `python main.py`.
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 10. Update dependency management and cleanup
  - [ ] 10.1 Update `requirements.txt` with pinned dependencies per layer
    - Ensure every third-party package is listed with exact version pinning (`==`)
    - Verify layer dependency boundaries: data (stdlib only), parsers (beautifulsoup4), scrapers (selenium, requests), bot (python-telegram-bot, python-dotenv), visualization (matplotlib, cartopy, pillow, shapely), core/logging (rich)
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7_

  - [ ] 10.2 Remove original flat module files from project root
    - Remove `notam_db.py`, `notam_parser.py`, `notam_request.py`, `fetch_faa_advisory.py`, `fetch_starbase_closures.py`, `telegram_bot.py`, `visualize_notams.py`, `notam_logging.py` from the project root
    - Keep `test_api.py` at root or move to `tests/` directory
    - Verify backward-compatible imports still work via `starship_notam/__init__.py` re-exports
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [ ] 11. Write unit tests for each layer
  - [ ] 11.1 Create test infrastructure and `tests/conftest.py`
    - Create `tests/` directory structure: `tests/unit/test_parsers/`, `tests/unit/test_data/`, `tests/unit/test_bot/`, `tests/unit/test_visualization/`, `tests/integration/`
    - Create `tests/conftest.py` with shared fixtures (in-memory SQLite DB, sample NOTAM text, sample HTML strings)
    - Add `pytest`, `pytest-asyncio` to dev dependencies
    - _Requirements: 9.1, 9.2, 9.3_

  - [ ] 11.2 Write parser layer unit tests
    - Create `tests/unit/test_parsers/test_notam_parser.py` — test `parse_notam` and `parse_carf_message` with known inputs
    - Create `tests/unit/test_parsers/test_coord_parser.py` — test DMS, decimal, and polygon coordinate parsing
    - Create `tests/unit/test_parsers/test_faa_parser.py` — test `parse_faa_advisory_html` with sample HTML
    - Create `tests/unit/test_parsers/test_starbase_parser.py` — test `parse_starbase_html` with sample HTML
    - Assert deterministic outputs given identical inputs
    - _Requirements: 3.6, 9.1, 9.4_

  - [ ] 11.3 Write data layer unit tests
    - Create `tests/unit/test_data/test_notam_repo.py` — test save/load round-trips with in-memory SQLite
    - Create `tests/unit/test_data/test_faa_repo.py` — test FAA activity persistence
    - Create `tests/unit/test_data/test_starbase_repo.py` — test beach/road alert persistence
    - Test error handling: verify exceptions are raised on failures, no partial commits
    - _Requirements: 2.5, 9.2_

  - [ ] 11.4 Write bot formatting unit tests
    - Create `tests/unit/test_bot/test_formatting.py` — test all formatting functions with known input dicts
    - Verify formatting module can be imported without Telegram API available
    - _Requirements: 5.1, 5.5_

- [ ] 12. Write integration tests
  - [ ] 12.1 Write import isolation and dependency boundary tests
    - Create `tests/integration/test_import_isolation.py` — verify parsers import without DB/Selenium/Telegram
    - Create `tests/integration/test_dependency_boundaries.py` — walk source files and assert no forbidden imports per layer
    - Verify import completes within 2 seconds for each layer
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 10.8_

  - [ ] 12.2 Write backward compatibility tests
    - Create `tests/integration/test_backward_compat.py` — verify every previously-public function is accessible from both old-style and new package paths
    - Test that `from starship_notam.data import save_notam` and equivalent old paths resolve correctly
    - _Requirements: 1.3, 8.3_

- [ ] 13. Final checkpoint - Ensure all tests pass
  - Run full test suite with `pytest`
  - Verify application starts correctly
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- This is a refactoring task — all existing runtime behavior must be preserved
- The `parsers` package is a pure-function layer with no I/O and deterministic outputs
- Heavy dependencies (Selenium, Cartopy, Matplotlib, python-telegram-bot) use lazy imports inside function bodies
- The `bot.orchestrator` is the only module that ties all layers together
- Backward-compatible re-exports in `starship_notam/__init__.py` ensure existing scripts continue working
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation of the refactoring

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "2.2", "2.3", "2.4", "3.1"] },
    { "id": 2, "tasks": ["3.2", "3.3", "3.4", "4.1"] },
    { "id": 3, "tasks": ["4.2", "4.3", "5.1"] },
    { "id": 4, "tasks": ["5.2", "7.1"] },
    { "id": 5, "tasks": ["7.2", "7.3"] },
    { "id": 6, "tasks": ["8.1", "8.2"] },
    { "id": 7, "tasks": ["8.3", "10.1"] },
    { "id": 8, "tasks": ["10.2", "11.1"] },
    { "id": 9, "tasks": ["11.2", "11.3", "11.4"] },
    { "id": 10, "tasks": ["12.1", "12.2"] }
  ]
}
```
