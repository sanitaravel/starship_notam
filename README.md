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

New or changed items are stored in a SQLite database, so each one is posted
only once.

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

### Running locally

Set `DEBUG_MODE=1` in `.env` so Selenium launches a local Chrome. Then:

```sh
python prefill_compass.py         # once, so the existing COMPASS files are not announced
python -m starship_notam          # or: python main.py, or: starship-notam
```

### Running in Docker

Leave `DEBUG_MODE` unset. Selenium then connects to a Selenium grid at
`http://selenium:4444/wd/hub`, so the stack needs a `selenium` service, for
example `selenium/standalone-chrome`. Put the database on a volume, e.g.
`NOTAM_DB_PATH=/app/data/notams.db`.

## Tests

```sh
pip install -e ".[dev]"
pytest
```

## Project layout

```text
starship_notam/
  core/           configuration (.env) and logging
  scrapers/       fetch raw data from each source
  parsers/        turn raw HTML/JSON/NOTAM text into dicts
  data/           SQLite schema and one repository per source
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
