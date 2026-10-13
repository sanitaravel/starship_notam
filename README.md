# Starship NOTAM bot

A Telegram bot that watches public sources for SpaceX Starship activity and
posts updates to a Telegram channel. On a fixed schedule it checks:

| Source | What it tracks |
| --- | --- |
| [FAA NOTAM Search](https://notams.aim.faa.gov/notamSearch/) | NOTAMs mentioning Starship; each one is posted as a map card |
| [FAA ATCSCC advisories](https://www.fly.faa.gov/adv/adv_spt) | Planned launch/re-entry windows |
| [Starbase beach & road access](https://www.starbase.texas.gov/beach-road-access) | Beach and road closures |
| [FCC ELS](https://apps.fcc.gov/oetcf/els/reports/GenericSearch.cfm) | SpaceX experimental licence applications |
| [FAA DRS](https://drs.faa.gov) | Changes to the Starship launch licence |
| [COMPASS (CADENA ATFM)](https://compass.atfm.aero) | New files on the Master Slide Deck page |

New or changed items are stored in a database (SQLite or PostgreSQL), so each
one is posted only once.

## Requirements

- Python 3.12+
- Google Chrome. The NOTAM search, FCC ELS and FAA DRS scrapers drive a
  headless browser through Selenium.
- A Telegram bot token from [@BotFather](https://t.me/BotFather). The bot must
  be an admin of the target channel with permission to post.

## Setup

```sh
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -e .                  # or ".[lock]" for the fully pinned environment
cp .env.example .env              # then fill in TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID
```

All settings are documented in [`.env.example`](.env.example).

### Run mode

`RUN_MODE` says where the bot runs:

| `RUN_MODE` | Selenium |
| --- | --- |
| `docker` (default) | Connects to the Selenium grid at `http://selenium:4444/wd/hub` |
| `standalone` | Launches a local Chrome |

### Database

By default the bot uses a SQLite file (`NOTAM_DB_PATH`, default `notams.db`).
To use PostgreSQL instead, install the extra and set `DATABASE_URL`:

```sh
pip install -e ".[postgres]"
```

```sh
DATABASE_URL=postgresql://notam:secret@localhost:5432/notam
```

The tables are created on startup. Data is not copied from an existing
SQLite file.

### Running locally

Set `RUN_MODE=standalone` in `.env`, then:

```sh
python prefill_compass.py         # once, so the existing COMPASS files are not announced
python -m starship_notam          # or: python main.py, or: starship-notam
```

### Running in Docker

[`compose.yaml`](compose.yaml) runs the bot with a Selenium Chrome container:

```sh
cp .env.example .env              # fill in TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID and POSTGRES_PASSWORD
docker compose up -d --build
docker compose logs -f bot
```

The services start in order:

1. `postgres` (PostgreSQL 17) holds the bot's data, and `selenium`
   (`selenium/standalone-chrome`) is the browser the scrapers drive. The
   others wait until both are healthy.
2. `prefill` runs `prefill_compass.py --if-empty` and exits. On the first
   start it records the files already on the COMPASS slide list as posted, so
   they are not announced. Later starts skip it, so files uploaded while the
   bot was down are still posted.
3. `bot` starts after `prefill` exits successfully, and restarts unless stopped.

Compose reads `.env` but sets `RUN_MODE`, `DATABASE_URL` and the container
paths itself. `DATABASE_URL` is built from `POSTGRES_PASSWORD` (and optionally
`POSTGRES_USER` and `POSTGRES_DB`). The database, logs, rendered maps and the
cartopy map data are kept in named volumes (`postgres`, `logs`, `maps`,
`cartopy`). PostgreSQL is not published to the host; to query it, run
`docker compose exec postgres psql -U notam`. `.env` is not copied into the
image.

**The first start posts everything that is currently active.** A new database
treats all current NOTAMs, FAA advisories and closures as new, so they are all
posted to the channel in the first cycle.

## Tests

```sh
pip install -e ".[dev]"
pytest
```

The PostgreSQL tests in `tests/unit/test_data/test_postgres.py` are skipped
unless `TEST_DATABASE_URL` points at a disposable PostgreSQL database. They
drop and recreate the bot's tables. CI runs them against a PostgreSQL service.

## Project layout

```text
starship_notam/
  core/           configuration (.env) and logging
  scrapers/       fetch raw data from each source
  parsers/        turn raw HTML/JSON/NOTAM text into dicts
  data/           database schema (SQLite/PostgreSQL) and one repository per source
  visualization/  map rendering and NOTAM card images
  bot/            message formatting, Telegram transport, main loop
tests/            unit and integration tests (pytest + Hypothesis)
```

`bot/orchestrator.py` is the only module that ties the layers together. The
layer boundaries are checked by `tests/integration/test_dependency_boundaries.py`.

## Contributing

All work goes through pull requests:

1. Branch off `development` (e.g. `feat/...`, `fix/...`) and open a pull
   request into `development`.
2. CI runs the test suite on every pull request. A pull request can be merged
   only when the `tests` check passes.
3. To release, open a pull request from `development` into `main`. `main`
   accepts pull requests **only from `development`**. The `source-branch`
   check fails for any other branch, and `tests` must pass. Merge it with a
   merge commit (squash and rebase are disabled on `main`) so the two
   branches keep the same history.

Direct pushes, force pushes and deletion are blocked on both `main` and
`development`.
