# Requirements Document

## Introduction

This feature adds a new data source to the existing `starship_notam` Telegram bot: the FCC Experimental Licensing System (ELS) Generic Search. The bot performs an automated Selenium search of the FCC ELS Generic Search page for license applications filed by SpaceX, follows each result's detail link, extracts application fields, persists them to the SQLite database with hash-based change detection, and posts new or updated applications to the configured Telegram chats.

The feature MUST follow the project's existing strict layered architecture:

- A new **scraper** drives Selenium against the FCC ELS site, delegates HTML parsing to a **parser**, performs no persistence, and returns shape-consistent empty results on failure.
- A new **parser** provides pure functions that transform HTML strings into structured dictionaries with no network, database, or filesystem I/O.
- A new **repository** in the data layer persists applications with SHA-256 payload-hash change detection and Telegram posting flags, and the schema is created in `connection.init_db()`.
- A new **formatting** function turns an application dictionary into a Russian-language HTML message string.
- The **orchestrator** integrates the new fetch → persist → post flow into its scheduled cycle with defensive error handling, delegating blocking Selenium work to `asyncio.to_thread`.

This document defines what the feature must do. Implementation details (specific selectors, table structure, exact column mapping) are deferred to the design phase.

## Glossary

- **ELS_Scraper**: The Selenium-driven scraper module (`scrapers/fcc_els_fetcher.py`) that performs the FCC ELS Generic Search, follows detail links, delegates parsing, and returns a list of application dictionaries without persisting.
- **ELS_Parser**: The pure-function parser module (`parsers/fcc_els_parser.py`) that transforms FCC ELS results-page HTML and STA_Print detail-page HTML into structured dictionaries.
- **ELS_Repository**: The data-layer module (`data/fcc_els_repo.py`) that persists FCC ELS applications and provides `save_*`, `get_*_needing_post`, and `mark_*_posted` functions.
- **ELS_Formatter**: The pure formatting function in `bot/formatting.py` that renders an FCC ELS application dictionary into a Russian-language HTML message string.
- **Orchestrator**: The existing `bot/orchestrator.py` module, the only module permitted to import across packages, which drives the fetch → persist → post cycle on a schedule.
- **FCC_ELS_Search_Page**: The FCC ELS Generic Search page at `https://apps.fcc.gov/oetcf/els/reports/GenericSearch.cfm`.
- **Detail_Page**: The STA_Print application detail page reached via a result row's "View Form → Current" link (e.g. `https://apps.fcc.gov/oetcf/els/reports/STA_Print.cfm?mode=current&application_seq=...&RequestTimeout=1000`).
- **Application**: A single FCC ELS license application record, identified by its File Number and/or its `application_seq` value.
- **Application_Seq**: The numeric `application_seq` query-parameter value that identifies an application on its Detail_Page.
- **File_Number**: The FCC file number column value from the results table, used as the primary persistence key for an Application.
- **Payload_Hash**: A SHA-256 hash of the JSON-serialised Application payload, used to distinguish new, updated, and unchanged Applications.
- **Search_Term**: The licensee name value entered into the search form; for this feature the value is "Space Exploration".
- **Receipt_Date_From**: The start of the receipt-date search range, computed as the current date minus one month, formatted as `mm/dd/yyyy`.
- **Receipt_Date_To**: The end of the receipt-date search range, computed as the current date, formatted as `mm/dd/yyyy`.
- **Record_Limit**: The maximum number of records the search requests, set to 50.
- **Telegram_Chat**: A chat destination resolved by the Orchestrator to which messages are delivered.

## Requirements

### Requirement 1: Perform the FCC ELS Generic Search

**User Story:** As a bot operator, I want the bot to run an automated FCC ELS Generic Search for SpaceX applications over a rolling one-month window, so that recently filed or updated applications are discovered.

#### Acceptance Criteria

1. WHEN the ELS_Scraper is invoked, THE ELS_Scraper SHALL open the FCC_ELS_Search_Page using Selenium and wait up to 30 seconds for the licensee-name, receipt-date-from, receipt-date-to, and show-records fields to become present and interactable.
2. IF the FCC_ELS_Search_Page does not become loaded, defined as all four search fields present and interactable, within 30 seconds, THEN THE ELS_Scraper SHALL abort the search, retain no partial results, and return an error result indicating the search page failed to load.
3. WHEN the FCC_ELS_Search_Page is loaded, THE ELS_Scraper SHALL enter the Search_Term "Space Exploration" into the licensee-name field.
4. WHEN the FCC_ELS_Search_Page is loaded, THE ELS_Scraper SHALL enter the Receipt_Date_From value, computed as the current date minus one month in `mm/dd/yyyy` format, into the receipt-date-from field.
5. WHEN the FCC_ELS_Search_Page is loaded, THE ELS_Scraper SHALL enter the Receipt_Date_To value, computed as the current date in `mm/dd/yyyy` format, into the receipt-date-to field.
6. WHEN the FCC_ELS_Search_Page is loaded, THE ELS_Scraper SHALL set the show-records field to the Record_Limit value of 50.
7. WHEN all four search fields have been populated with their specified values, THE ELS_Scraper SHALL submit the search.
8. WHEN the search has been submitted, THE ELS_Scraper SHALL wait up to 30 seconds for the results table to become present before proceeding.
9. IF the results table does not become present within 30 seconds after submission, THEN THE ELS_Scraper SHALL abort processing, retain no partial results, and return an error result indicating the results table failed to load.
10. THE ELS_Scraper SHALL import Selenium lazily inside the scraper function so that importing the scrapers package does not require Selenium to be installed.

### Requirement 2: Extract application rows from the results page

**User Story:** As a bot operator, I want the bot to read each application row returned by the search, so that every matching application can be processed.

#### Acceptance Criteria

1. WHEN the search results page has loaded, THE ELS_Scraper SHALL identify each application row in the results table.
2. THE ELS_Parser SHALL accept the results-page HTML string and return a list of dictionaries, one per application row.
3. WHEN a result row is parsed, THE ELS_Parser SHALL extract the File_Number, Call Sign, Applicant Name, Receipt Date, Status, and Status Date values for that row, trimming leading and trailing whitespace from each value.
4. IF a result row's Call Sign value is blank or "N/A", THEN THE ELS_Parser SHALL represent that Call Sign as an empty string.
5. WHEN a result row is parsed, THE ELS_Parser SHALL extract the "View Form → Current" Detail_Page link for that row.
6. WHEN a result row is parsed, THE ELS_Parser SHALL extract the Application_Seq value from the application_seq parameter of that row's Detail_Page link.
7. IF a result row is missing a File_Number, a Current Detail_Page link, or an Application_Seq value, THEN THE ELS_Parser SHALL exclude that row from the returned list and record an indication of the excluded row.
8. IF the search returns no application rows, THEN THE ELS_Parser SHALL return an empty list.

### Requirement 3: Follow each detail link and extract application fields

**User Story:** As a bot operator, I want the bot to open each application's current form detail page and read its fields, so that posted messages contain complete application information.

#### Acceptance Criteria

1. WHILE processing result rows, THE ELS_Scraper SHALL request each row's "Current" Detail_Page within a 30-second per-request timeout.
2. IF a Detail_Page request does not return a response within 30 seconds, THEN THE ELS_Scraper SHALL retry the request up to 3 times before treating the request as failed.
3. WHEN a Detail_Page has been retrieved with a successful response, THE ELS_Scraper SHALL pass the complete Detail_Page HTML string to the ELS_Parser.
4. WHEN a Detail_Page HTML string is parsed, THE ELS_Parser SHALL return a dictionary containing each application field present on that Detail_Page, using the field label as the key and its extracted text value as the value.
5. IF a Detail_Page HTML string contains no recognizable application fields, THEN THE ELS_Parser SHALL return an empty dictionary.
6. WHEN an Application dictionary is produced, THE ELS_Scraper SHALL include the File_Number and Application_Seq values as entries in that dictionary.
7. IF a single Detail_Page request fails after all retry attempts, or a parse operation fails, THEN THE ELS_Scraper SHALL record a log entry indicating the failing File_Number and the failure cause, discard that row's partial data, and continue processing the remaining rows.

### Requirement 4: Return results without persistence and fail safely

**User Story:** As a developer, I want the ELS_Scraper to follow the existing scraper conventions, so that the layered architecture is preserved and one failure does not crash the caller.

#### Acceptance Criteria

1. WHEN the ELS_Scraper completes without an unrecoverable error, THE ELS_Scraper SHALL return a list of Application dictionaries, each dictionary containing at least the File_Number and Application_Seq values.
2. THE ELS_Scraper SHALL delegate all HTML parsing of results-page and Detail_Page HTML to the ELS_Parser.
3. THE ELS_Scraper SHALL perform no writes to the database.
4. IF the search submission or results-page navigation fails, THEN THE ELS_Scraper SHALL return an empty list and SHALL raise no exception to the caller.
5. WHEN the ELS_Scraper returns after a successful run, THE ELS_Scraper SHALL close the Selenium browser session before returning.
6. IF the ELS_Scraper terminates due to any error after the Selenium browser session was opened, THEN THE ELS_Scraper SHALL close that Selenium browser session before returning.
7. THE ELS_Parser SHALL perform no network, database, or filesystem operations.

### Requirement 5: Persist applications with change detection

**User Story:** As a bot operator, I want applications stored with new-versus-updated-versus-unchanged detection, so that the bot posts each change once and avoids duplicate posts.

#### Acceptance Criteria

1. THE ELS_Repository SHALL persist each Application keyed uniquely by its File_Number.
2. WHEN an Application is saved, THE ELS_Repository SHALL compute a Payload_Hash as the SHA-256 hash of the JSON-serialised Application payload produced with sorted keys so the hash is deterministic.
3. IF no stored Application exists for the File_Number, THEN THE ELS_Repository SHALL insert the Application with `created_at` and `updated_at` set to the current time, the computed Payload_Hash, and `telegram_posted` set to 0.
4. IF a stored Application exists for the File_Number AND the stored Payload_Hash equals the computed Payload_Hash, THEN THE ELS_Repository SHALL leave the stored fields and the Telegram posting state of the Application unchanged.
5. IF a stored Application exists for the File_Number AND the stored Payload_Hash differs from the computed Payload_Hash, THEN THE ELS_Repository SHALL update the stored fields, set `updated_at` to the current time, store the new Payload_Hash, and set `telegram_posted` to 0 so the Application is re-posted.
6. THE ELS_Repository SHALL store `telegram_posted`, `telegram_posted_at`, and `telegram_message_id` fields for each Application.
7. IF persisting an Application fails, THEN THE ELS_Repository SHALL raise an error to the caller and SHALL not leave the row in a partially written state.
8. THE Orchestrator SHALL ensure the FCC ELS application table exists before the scheduled cycle runs by initialising the database through `init_db`.

### Requirement 6: Create the FCC ELS database schema

**User Story:** As a developer, I want the FCC ELS table schema created and migrated in the data layer, so that persistence follows the existing connection-layer convention.

#### Acceptance Criteria

1. WHEN `init_db` runs AND the FCC ELS application table does not exist, THE `connection.init_db` function SHALL create the FCC ELS application table.
2. WHEN `init_db` runs AND the FCC ELS application table already exists, THE `connection.init_db` function SHALL leave the existing table and its stored rows unchanged.
3. WHEN `init_db` creates the FCC ELS application table, THE `connection.init_db` function SHALL define columns for `File_Number`, `Application_Seq`, the extracted application fields, `created_at`, `updated_at`, `payload_hash`, `telegram_posted`, `telegram_posted_at`, and `telegram_message_id`, where `telegram_posted` is an integer flag defaulting to 0 and the timestamp and message-id columns are text.
4. WHEN `init_db` creates the FCC ELS application table, THE `connection.init_db` function SHALL enforce a uniqueness constraint on `File_Number` such that inserting a second row with an existing `File_Number` value is rejected.
5. WHEN `init_db` runs AND the FCC ELS application table exists but is missing one or more of the columns listed in criterion 3, THE `connection.init_db` function SHALL add each missing column via an additive migration without dropping or recreating the table.
6. IF an error occurs while creating or migrating the FCC ELS application table, THEN THE `connection.init_db` function SHALL roll back the pending transaction so the database is not left in a partially committed state and SHALL propagate an error indicating the initialization failure.

### Requirement 7: Post new and updated applications to Telegram

**User Story:** As a subscriber, I want to receive a Telegram message for each new or updated SpaceX FCC application, so that I stay informed of licensing activity.

#### Acceptance Criteria

1. THE ELS_Repository SHALL provide a function that returns the Applications that are not currently marked as posted.
2. WHEN the Orchestrator retrieves one or more Applications needing a post, THE Orchestrator SHALL render each Application into a message string using the ELS_Formatter before attempting delivery.
3. THE ELS_Formatter SHALL return an HTML-formatted Russian-language message string built from an Application dictionary, using HTML tags consistent with the existing formatters (e.g. "<b>...</b>").
4. WHEN a message has been rendered, THE Orchestrator SHALL send the message to each resolved Telegram_Chat through the transport layer, pausing 5 seconds between consecutive chats.
5. WHEN an Application has been sent successfully to one or more Telegram_Chats, THE Orchestrator SHALL mark that Application as posted through the ELS_Repository, recording the current UTC time and the Telegram message identifier returned by the transport layer.
6. IF sending a rendered message to a Telegram_Chat fails, THEN THE Orchestrator SHALL log the failure, continue sending to the remaining resolved Telegram_Chats, and not treat that failed send as a successful delivery.
7. IF a rendered message could not be sent successfully to any resolved Telegram_Chat, THEN THE Orchestrator SHALL not mark the Application as posted, so the Application is retried on the next cycle.
8. IF no Applications need a Telegram post, THEN THE Orchestrator SHALL complete the FCC ELS step without sending a message.
9. THE ELS_Formatter SHALL perform no network I/O.

### Requirement 8: Integrate into the scheduled orchestration cycle

**User Story:** As a bot operator, I want the FCC ELS flow to run automatically on the existing schedule without destabilising other data sources, so that monitoring continues reliably.

#### Acceptance Criteria

1. WHEN the Orchestrator runs one ingestion-and-delivery cycle, THE Orchestrator SHALL execute the FCC ELS fetch, persist, and post steps.
2. WHEN the Orchestrator invokes the ELS_Scraper, THE Orchestrator SHALL run the blocking Selenium work in a worker thread via `asyncio.to_thread`.
3. IF the FCC ELS fetch step fails, THEN THE Orchestrator SHALL log the failure and continue running the remaining steps of the cycle.
4. IF persisting a single Application fails, THEN THE Orchestrator SHALL log the failure and continue processing the remaining Applications.
5. IF sending or marking a single Application fails, THEN THE Orchestrator SHALL log the failure and continue processing the remaining Applications.
6. IF the entire FCC ELS step raises an unexpected error, THEN THE Orchestrator SHALL log the error and complete the cycle without terminating the main loop.

### Requirement 9: Follow existing layered module conventions

**User Story:** As a maintainer, I want the FCC ELS feature to match the existing package structure and import rules, so that the codebase stays consistent and testable.

#### Acceptance Criteria

1. THE ELS_Scraper SHALL reside in the `scrapers` package, and its module-level imports SHALL reference only the `parsers` package, the `core` package, the Python standard library, and the third-party libraries permitted for the scrapers layer, with any other third-party dependency imported lazily inside function bodies.
2. THE ELS_Parser SHALL reside in the `parsers` package, and its module-level imports SHALL reference only the `core` package, the Python standard library, and the third-party libraries permitted for the parsers layer, with no module-level import referencing the `data` or `visualization` packages.
3. THE ELS_Repository SHALL reside in the `data` package, and its module-level imports SHALL reference only `data.connection`, the `core` package, and the Python standard library, with no module-level third-party import.
4. THE ELS_Formatter SHALL reside in `bot/formatting.py`, and its module-level imports SHALL reference only the Python standard library.
5. WHEN a new public ELS function is added to the `scrapers`, `data`, or `bot/formatting` module, THE affected `__init__` module SHALL re-import that function and list its name in the module's `__all__` collection, matching the existing export pattern.
6. THE Orchestrator SHALL be the only module whose module-level imports reference the ELS_Scraper, ELS_Repository, and ELS_Formatter together.
7. WHEN the `scrapers`, `parsers`, `data`, or `bot` package containing new ELS code is imported in isolation, THE package SHALL complete the import within 2 seconds without raising an ImportError and without loading the heavy optional dependencies belonging to other layers.
