# AGENTS.md

Guide for coding agents working on starship_notam. `README.md` covers setup
and deployment for people; this file covers how the code is built and the
rules for changing it.

## What this is

A Python 3.12 bot that watches Starship-related sources and posts new items
to one Telegram channel, in Russian. Sources: FAA NOTAMs (map cards), FAA
ATCSCC advisories, Starbase beach and road closures, FCC ELS, the FAA DRS
launch licence, COMPASS, the Federal Register, Regulations.gov, SEC EDGAR and
USCG Broadcast Notices to Mariners (map cards). Each item is stored in SQLite
or PostgreSQL and posted once.

`docs/source-research.md` holds the research behind each source: endpoints,
response formats, filtering rules and edge cases. Read it before you change a
source or add one.

## Layout

| Path | Contents |
| --- | --- |
| `src/core/` | `config.py` (env vars, URLs, source settings), `logging.py` |
| `src/scrapers/` | Fetchers: `HttpFetcher` subclasses for HTTP sources, Selenium functions for the rest |
| `src/parsers/` | Pure parsing functions: text/JSON/XML in, dicts out |
| `src/data/` | `schema.py` (tables, column migrations, `init_db`), one repository per source |
| `src/bot/formatting/` | Telegram HTML messages, one module per source |
| `src/bot/orchestrator/` | One module per source (fetch, save, post), `loop.py` runs them all each cycle |
| `src/bot/transport.py` | The only module that talks to the Telegram API |
| `src/visualization/` | Map rendering (Cartopy) and the PIL card shared by NOTAMs and BNMs |
| `prefill_*.py` | One-off scripts that mark everything a source lists now as already posted |
| `tests/unit/`, `tests/integration/` | pytest suite |

## Layer rules

- `parsers` are pure: no network, database or file access, and no imports
  from `data` or `visualization`.
- Scrapers never persist and never raise on a failed request: they log it and
  return `None` (or the fetcher's `failure()` value).
- Only `bot/orchestrator` combines layers (scrapers, data, visualization,
  formatting, transport).
- Each layer may import only its own third-party packages at module level
  (`core`: rich, dotenv; `data`: standard library only, psycopg lazily;
  `parsers`: bs4; `scrapers`: selenium, requests; `bot`:
  telegram, dotenv; `visualization`: matplotlib, cartopy, PIL, shapely). Heavy
  packages are imported lazily inside functions.
  `tests/integration/test_dependency_boundaries.py` enforces this.
- Blocking work (HTTP, Selenium, rendering) runs in `asyncio.to_thread` from
  the orchestrator. Every step catches its own exceptions, so one failing
  source never stops the loop.

## Adding a source

Copy the shape of the closest existing source end to end. SEC EDGAR,
Regulations.gov and USCG BNM are the most recent.

1. `src/core/config.py`: URLs, keys and source settings. A source that needs
   a key is skipped with a log line while the key is unset.
2. `src/scrapers/<name>_fetcher.py`: an `HttpFetcher` subclass plus a
   module-level instance (e.g. `sec_edgar_filings_fetcher`).
3. `src/parsers/<name>_parser.py`: pure functions, documented with a sample
   of the real input.
4. `src/data/<name>_repo.py`: a `PostedItemRepository` subclass plus a
   module-level instance. Add the table to `_SCHEMA` in `src/data/schema.py`
   (columns added to an existing table go in `_ADDED_COLUMNS`).
5. `src/bot/formatting/<name>.py`: Russian HTML, every source-supplied string
   passed through `html.escape`, hashtags from `_common.py` at the end. Photo
   captions must fit 1024 characters.
6. `src/bot/orchestrator/<name>.py`: fetch, save oldest first, then
   `post_pending(...)` (pass `photo_fn` for a map card). Add the step to
   `generate_and_send` in `loop.py`, and a `prefill_<name>_...()` function.
7. `prefill_<name>.py` with `--if-empty`, added to the `prefill` service in
   `compose.yaml` and to the `COPY` line in `Dockerfile`.
8. Re-export new public names from each package `__init__.py`.
9. Tests: parser tests built from real source text, repository tests,
   formatting/posting/prefill tests. Also update the step list in
   `tests/unit/test_bot/test_main_loop.py`, `_TABLES` in
   `tests/unit/test_data/test_postgres.py`, and add a pinned case to
   `tests/unit/test_data/test_repository_hashes.py`.
10. Docs: the sources table and prefill steps in `README.md`, an
    `> **Implemented**` note in `docs/source-research.md`, and every new env
    var in `.env.example`.

## Code style

- Match the surrounding code: comment density, naming, docstring style
  (module docstrings describe the source and the public API).
- Expose module-level instances (`compass_files`, `faa_advisory_fetcher`), not
  `def` wrappers that build a class and call one method. Name instances so
  they don't shadow their own module when re-exported.
- Changing what a repository hashes makes every stored row look changed. The
  pinned hashes in `test_repository_hashes.py` catch this; don't update them
  for an existing source without a migration plan.
- Telegram messages are in Russian; code, comments and docs are in English.

## Commands

```sh
pip install -e ".[dev]"            # add ",postgres" for the PostgreSQL tests
pytest                             # full suite, about 3 minutes; uses .env.test
pytest tests/unit/test_parsers     # one layer
python -m src                      # run the bot (needs a real .env)
```

`src/core/config.py` loads `.env` with `override=True`, so env vars passed
inline lose to the real `.env`. For any manual run (live fetch checks,
prefill scripts), select the test env file and clean up afterwards:

```sh
NOTAM_ENV_FILE=.env.test NOTAM_LOG_DIR=logs/test python prefill_sec_edgar.py
rm -f test_notams.db; rm -rf logs/test
```

Never run anything against the real `.env` or `notams.db`: it could post to
the live channel or mark real items as posted. Tests set `TEST_DATABASE_URL`
to run the PostgreSQL cases; without it they are skipped.

## Git and PRs

- Branch from `origin/development`. Use Conventional Commit messages
  (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `ci:`, `chore:`, with an
  optional scope such as `feat(data):`). The body says what changed and why.
- `development` accepts pull requests only (a ruleset blocks direct pushes).
  Open the PR into `development`.
- `main` accepts pull requests only from `development`
  (`.github/workflows/branch-policy.yml`). Releases are timed by the
  maintainer; don't open or merge a release PR unless asked.
- CI (`.github/workflows/ci.yml`) runs tests only on PRs into `main`, so run
  `pytest` yourself before opening a PR into `development`. A merge into
  `main` builds the image the server deploys.
