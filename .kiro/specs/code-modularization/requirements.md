# Requirements Document

## Introduction

This document specifies requirements for refactoring the Starship NOTAM monitoring and Telegram bot project from a flat file structure into a well-organized package-based architecture. The current codebase consists of 9 Python modules at the project root with tightly coupled imports, mixed responsibilities, and no clear separation of concerns. The refactoring aims to improve maintainability, testability, and extensibility without changing external behavior.

## Glossary

- **Project**: The starship_notam Python application that monitors NOTAMs, FAA advisories, and Starbase closures, then sends formatted alerts via Telegram
- **Module**: A single Python file (.py) containing related functions and classes
- **Package**: A directory containing an `__init__.py` file and one or more modules, forming a logical grouping
- **Data_Layer**: The package responsible for database operations and data persistence (currently `notam_db.py`)
- **Parser_Layer**: The package responsible for parsing NOTAM text, coordinates, and external data sources (currently `notam_parser.py`, `fetch_faa_advisory.py`, `fetch_starbase_closures.py`)
- **Scraper_Layer**: The package responsible for fetching raw data from external services via HTTP or Selenium (currently `notam_request.py`, `fetch_faa_advisory.py`, `fetch_starbase_closures.py`)
- **Bot_Layer**: The package responsible for Telegram bot communication and message formatting (currently `telegram_bot.py`)
- **Visualization_Layer**: The package responsible for rendering NOTAM map images (currently `visualize_notams.py`)
- **Logging_Module**: The shared logging configuration module (currently `notam_logging.py`)
- **Entry_Point**: The top-level script or module invoked to start the application

## Requirements

### Requirement 1: Package Structure

**User Story:** As a developer, I want the codebase organized into logical packages, so that I can navigate and understand the project structure quickly.

#### Acceptance Criteria

1. THE Project SHALL be organized into a top-level `starship_notam` Python package containing an `__init__.py` and sub-packages for each functional area listed in criterion 2
2. THE Project SHALL contain the following sub-packages: `data` (database access), `parsers` (NOTAM and message parsing), `scrapers` (web scraping and external data fetching), `bot` (Telegram bot logic), `visualization` (map and image rendering), and a shared `core` package exposing the project logger and environment-based configuration values
3. WHEN the refactored package is imported, THE Project SHALL re-export from `starship_notam.__init__` every public function and object that was previously importable from the top-level flat modules (`notam_db`, `notam_parser`, `notam_request`, `notam_logging`, `telegram_bot`, `visualize_notams`, `fetch_faa_advisory`, `fetch_starbase_closures`) so that existing `from <module> import <name>` statements continue to resolve without modification
4. THE Project SHALL include a module-to-package mapping where `notam_db` maps to `data`, `notam_parser` maps to `parsers`, `notam_request` and `fetch_faa_advisory` and `fetch_starbase_closures` map to `scrapers`, `telegram_bot` maps to `bot`, `visualize_notams` maps to `visualization`, and `notam_logging` maps to `core`

### Requirement 2: Data Layer Separation

**User Story:** As a developer, I want all database logic isolated in a dedicated package, so that I can modify persistence concerns without affecting business logic.

#### Acceptance Criteria

1. THE Data_Layer SHALL contain all SQLite database initialization, connection management, and schema migration logic in a single dedicated Python module that does not import from Telegram, parsing, or visualization modules
2. THE Data_Layer SHALL provide separate modules for NOTAM persistence, FAA activity persistence, and Starbase alert persistence, where each module exposes only functions related to its specific domain entity
3. THE Data_Layer SHALL expose repository-style functions that accept and return plain Python dictionaries, and SHALL NOT import or reference any Telegram, parsing, or visualization modules
4. WHEN a database path is not explicitly provided, THE Data_Layer SHALL resolve the path by first reading the environment variable `NOTAM_DB_PATH`, and if that variable is not set, SHALL default to `notams.db` in the project root
5. IF a database operation fails due to connection error or write failure, THEN THE Data_Layer SHALL raise an exception to the caller without silently swallowing the error, and SHALL NOT leave the database in a partially committed state
6. THE application modules outside the Data_Layer SHALL NOT contain direct SQLite imports or raw SQL statements, delegating all database access through Data_Layer functions

### Requirement 3: Parser Layer Separation

**User Story:** As a developer, I want parsing logic isolated from I/O, so that I can test parsers in isolation with deterministic inputs.

#### Acceptance Criteria

1. THE Parser_Layer SHALL contain the NOTAM text parser (ICAO fields, CARF messages, Q-line parsing) in a dedicated Python module that accepts raw NOTAM text as a string parameter and returns a structured dictionary without performing any network, database, or filesystem operations
2. THE Parser_Layer SHALL contain the coordinate parser (DMS, decimal, polygon extraction) in a dedicated Python module that accepts coordinate strings as parameters and returns numeric latitude/longitude values or lists of coordinate dictionaries without performing any network, database, or filesystem operations
3. THE Parser_Layer SHALL contain the FAA advisory HTML parser in a dedicated Python module that accepts an HTML string as a parameter and returns a list of parsed launch dictionaries without performing any network, database, or filesystem operations
4. THE Parser_Layer SHALL contain the Starbase closure HTML parser in a dedicated Python module that accepts an HTML string as a parameter and returns a structured dictionary of beach and road closure data without performing any network, database, or filesystem operations
5. THE Parser_Layer SHALL depend only on Python standard library modules (including `re`, `datetime`, `zoneinfo`, and `typing`), and `beautifulsoup4`; it SHALL NOT import `requests`, database modules, Telegram modules, Selenium modules, or any module that performs network I/O, filesystem writes, or inter-process communication
6. WHEN any parser function in the Parser_Layer is invoked, THE Parser_Layer SHALL produce identical output given identical input strings, regardless of system clock, network state, or database state

### Requirement 4: Scraper Layer Separation

**User Story:** As a developer, I want data-fetching code separated from parsing, so that I can substitute mock responses during testing.

#### Acceptance Criteria

1. THE Scraper_Layer SHALL contain the Selenium-based FAA NOTAM search automation in a dedicated Python module that exposes a single public entry-point function accepting a search keyword string and returning results to the caller
2. THE Scraper_Layer SHALL contain HTTP-based fetchers for the FAA advisory page and Starbase status page in separate dedicated Python modules, each exposing a single public entry-point function that returns results to the caller
3. THE Scraper_Layer SHALL return raw HTML or structured response data as Python dictionaries or lists to the calling code without importing or invoking any database or persistence module
4. WHEN the Selenium scraper completes a search, THE Scraper_Layer SHALL return a list of dictionaries where each dictionary contains at minimum the keys: location, number, class, start_date_utc, end_date_utc, condition, and icao_message (string, may be empty)
5. WHEN the HTTP-based FAA advisory fetcher completes a request, THE Scraper_Layer SHALL return a list of dictionaries where each dictionary contains at minimum the keys: mission, primary_window, and backup_window
6. IF a network request fails or returns no results, THEN THE Scraper_Layer SHALL raise an exception or return an empty list without performing partial database writes, so that the caller can detect the failure

### Requirement 5: Bot Layer Separation

**User Story:** As a developer, I want Telegram bot logic isolated, so that I can modify message formatting or delivery without touching data-fetching code.

#### Acceptance Criteria

1. THE Bot_Layer SHALL contain message formatting functions (NOTAM captions, FAA activity text, road alerts, beach alerts) in a dedicated formatting module implemented as a separate Python file that does not import the Telegram API or perform network I/O
2. THE Bot_Layer SHALL contain Telegram API interaction functions (send photo, send message, chat management) in a dedicated transport module implemented as a separate Python file that does not import the formatting module or any data-fetching modules
3. THE Bot_Layer SHALL contain the main orchestration loop (scheduling, ingestion coordination) in a dedicated Python file that imports the formatting module and transport module but does not define formatting or transport logic inline
4. THE Bot_Layer SHALL NOT contain any NOTAM text parsing logic, database schema definitions, or coordinate extraction code; these SHALL remain in their respective data-layer modules
5. WHEN a developer modifies a formatting function signature or template, THEN THE Bot_Layer transport module and data-layer modules SHALL require zero code changes to remain functional

### Requirement 6: Visualization Layer Separation

**User Story:** As a developer, I want visualization code in its own package, so that I can update map rendering without risk to the bot or parser logic.

#### Acceptance Criteria

1. THE Visualization_Layer SHALL NOT contain coordinate parsing logic; it SHALL import the `parse_coords_from_text` function from the Parser_Layer
2. THE Visualization_Layer SHALL contain all Cartopy/Matplotlib map rendering logic (map projection, feature layers, coordinate plotting, extent calculation) in a dedicated module separate from image composition
3. THE Visualization_Layer SHALL contain the PIL-based image composition logic (canvas layout, fonts, text rendering) in a dedicated module separate from map rendering
4. THE Visualization_Layer SHALL expose a single public function `render_notam_image(notam_dict, output_path)` that produces a PNG image file at the specified `output_path`
5. IF `render_notam_image` receives a `notam_dict` with missing or unparseable coordinates, THEN THE Visualization_Layer SHALL still produce an image file using a default global map extent
6. IF `render_notam_image` encounters a rendering failure due to unavailable Cartopy or Matplotlib, THEN THE Visualization_Layer SHALL raise an exception indicating which dependency is missing
7. THE Visualization_Layer SHALL NOT import any modules from the Bot_Layer, Scraper_Layer, or Data_Layer

### Requirement 7: Shared Configuration and Logging

**User Story:** As a developer, I want centralized configuration and logging, so that all packages use consistent settings and log formatting.

#### Acceptance Criteria

1. THE core package SHALL provide a `config` module that loads environment variables and exposes them as typed constants: `TELEGRAM_BOT_TOKEN` (string), `CHAT_IDS` (list of strings parsed from a comma-separated value), `DB_PATH` (string), `KEYWORD` (string), and `RUNS_PER_HOUR` (integer)
2. IF a required environment variable (`TELEGRAM_BOT_TOKEN`) is not set or is empty at module load time, THEN THE config module SHALL raise an error indicating which variable is missing
3. THE core package SHALL define default values for optional configuration constants: `KEYWORD` defaults to "STARSHIP", `DB_PATH` defaults to "notams.db", and `RUNS_PER_HOUR` defaults to 2
4. THE core package SHALL provide the existing logging setup as a `logging` module that exposes a configured `logger` instance with both a console handler and a rotating file handler writing to `logs/notam.log`
5. WHEN any package needs configuration values, THE package SHALL import them from the core config module rather than calling `os.environ.get` directly

### Requirement 8: Import Compatibility

**User Story:** As a developer, I want the refactoring to preserve runtime behavior, so that the bot continues to work identically after restructuring.

#### Acceptance Criteria

1. THE Project SHALL provide a top-level entry point script (e.g., `main.py` or `__main__.py`) that starts the bot loop with the same behavior as the current `telegram_bot.py` invocation
2. WHEN the application is started, THE Project SHALL initialize the database, refresh Telegram chats, and enter the scheduled monitoring loop exactly as the current implementation does
3. IF an import error occurs due to a missing module after refactoring, THEN THE Project SHALL fail with a clear error message identifying the missing package or module

### Requirement 9: Test Infrastructure Compatibility

**User Story:** As a developer, I want the refactored modules to be independently importable, so that I can write unit tests for each layer without starting the full application.

#### Acceptance Criteria

1. WHEN a test imports only the Parser_Layer modules, THE Parser_Layer modules SHALL complete the import without any database file existing on disk, without establishing a database connection, and without triggering network requests as a side effect of the import
2. WHEN a test imports only the Data_Layer modules, THE Data_Layer modules SHALL complete the import within 2 seconds without Selenium, Telegram, or Cartopy packages installed in the Python environment
3. WHEN a test imports only the Visualization_Layer modules, THE Visualization_Layer modules SHALL complete the import within 2 seconds without a running Telegram bot instance, without an active network connection, and without requiring a valid TELEGRAM_BOT_TOKEN environment variable
4. THE Parser_Layer modules SHALL NOT contain module-level import statements that reference Data_Layer or Visualization_Layer modules
5. IF an optional dependency required by a layer is not installed, THEN THE importing layer SHALL raise an ImportError with a message indicating the missing package name only when a function requiring that dependency is called, not at module import time
6. WHEN a test imports any single layer in an isolated Python environment containing only that layer's dependencies, THE import SHALL succeed without raising ImportError or ModuleNotFoundError within 2 seconds

### Requirement 10: Dependency Management

**User Story:** As a developer, I want clear dependency boundaries between packages, so that I understand which external libraries each layer requires.

#### Acceptance Criteria

1. THE Project SHALL maintain a `requirements.txt` file at the repository root that lists every third-party package needed to install and run all layers, with each dependency pinned to an exact version (using `==`)
2. THE Data_Layer SHALL import only from the Python standard library (`sqlite3`, `json`, `hashlib`, `datetime`, `os`, `pathlib`, `typing`) and from internal project modules
3. THE Parser_Layer SHALL import only from the Python standard library (`re`, `json`, `datetime`, `typing`) and from `beautifulsoup4`, plus internal project modules
4. THE Scraper_Layer SHALL depend on `selenium`, `requests`, and the Python standard library in addition to internal project modules
5. THE Bot_Layer SHALL depend on `python-telegram-bot`, `python-dotenv`, and the Python standard library in addition to internal project modules
6. THE Visualization_Layer SHALL depend on `matplotlib`, `cartopy`, `pillow`, and `shapely` in addition to the Python standard library and internal project modules
7. THE Logging_Module SHALL depend on `rich` and the Python standard library (`logging`, `pathlib`)
8. IF a module imports a third-party package not listed in its layer's allowed dependencies, THEN THE Project SHALL treat this as a dependency boundary violation
