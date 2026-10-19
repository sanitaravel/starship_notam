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
| [Federal Register](https://www.federalregister.gov/documents/search?conditions%5Bagencies%5D%5B%5D=federal-aviation-administration&conditions%5Bterm%5D=spacex&order=newest) | New FAA documents mentioning SpaceX (environmental reviews, comment periods, rules) |
| [Regulations.gov](https://www.regulations.gov/search?filter=Starship) | New FAA and USCG docket documents about Starship, with their PDFs: final EAs and FONSIs, safety zones, and other material the Federal Register does not print. Needs a free `REGULATIONS_GOV_API_KEY`; skipped without one |
| [SEC EDGAR](https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001181412) | New SpaceX (SPCX) filings: 8-K material events with their item names, 10-Q/10-K reports (with the Starship launch count) and securities offerings. Needs `SEC_USER_AGENT` with a contact address; skipped without one |
| [USCG Broadcast Notices to Mariners](https://www.navcen.uscg.gov/subscribe-email-rss-feeds) | Maritime hazard areas for Starship launches from the Heartland and Southeast District feeds, each posted as a map card with its UTC windows, then the cancellation with the outcome (e.g. a successful launch). Falcon 9 and other Cape launches are left out |

New or changed items are stored in a database (SQLite or PostgreSQL), so each
one is posted only once.

## Running with Docker (recommended)

[`compose.yaml`](compose.yaml) runs everything the bot needs: the bot, a
PostgreSQL database and a Selenium Chrome browser. You only need Docker.

The steps below run the bot by hand on any machine. To run it on a Linux
server that deploys every release from `main` automatically, follow
[docs/deployment.md](docs/deployment.md) instead.

### 1. Prerequisites

- Docker Engine with the Compose plugin (`docker compose version` should print
  v2.x), or Docker Desktop. It runs on amd64 and arm64.
- About 2 GB of free RAM. Chrome alone gets a 2 GB `/dev/shm`.
- A Telegram bot and a channel:
  1. Create a bot with [@BotFather](https://t.me/BotFather) and copy its token.
  2. Add the bot to your channel as an **administrator** with permission to
     post messages.
  3. Note the channel's id: its public `@username`, or the numeric `-100…` id
     for a private channel.

### 2. Get the code and configure it

```sh
git clone https://github.com/sanitaravel/starship_notam.git
cd starship_notam
cp .env.example .env
```

Open `.env` and fill in the three required values:

```sh
TELEGRAM_BOT_TOKEN=123456789:AA...        # from @BotFather
TELEGRAM_CHANNEL_ID=@my_starship_channel  # or -1001234567890
POSTGRES_PASSWORD=ChooseALongRandomPassword
```

- **`POSTGRES_PASSWORD`**: use letters and digits only, because it becomes
  part of a database URL. It is set when the database volume is first
  created, so changing it later in `.env` does not change the database's own
  password. To change it, reset the database (see below) or run
  `ALTER USER` in `psql`.
- **Other settings** in [`.env.example`](.env.example) are optional, such as
  `RUNS_PER_HOUR`.
- **Ignored under Compose:** `RUN_MODE`, `DATABASE_URL` and `NOTAM_DB_PATH`.
  Compose sets them for the containers itself, so a `.env` you also use for
  local runs works unchanged.
- **Not in the image:** `.env` is never copied into the image.

### 3. Start the bot

```sh
docker compose up -d --build
```

The services start in this order:

1. **`postgres`** (PostgreSQL 17) and **`selenium`**
   (`selenium/standalone-chrome`) start first. Everything else waits until
   both report healthy.
2. **`prefill`** runs `prefill_compass.py --if-empty`,
   `prefill_federal_register.py --if-empty`,
   `prefill_regulations_gov.py --if-empty`,
   `prefill_sec_edgar.py --if-empty` and
   `prefill_uscg_bnm.py --if-empty` once, and exits. On the very first
   start they record the files already on the COMPASS slide list, the
   documents already in the Federal Register and on Regulations.gov,
   SpaceX's existing SEC filings and the Starship notices to mariners in the
   Coast Guard feeds as posted, so the bot does not
   announce the whole existing back catalogue. On later starts they do
   nothing, so items published while the bot was down are still announced.
3. **`bot`** starts after `prefill` succeeds. It runs a check cycle
   immediately, then `RUNS_PER_HOUR` times per hour on the clock (by default
   at :00 and :30). It restarts automatically unless you stop it.

> **The first cycle posts everything that is currently active.** A new
> database treats all current NOTAMs, FAA advisories, closures and licence
> filings as new, so they are all posted to the channel in one go. After that
> only new or changed items are posted.

### 4. Check that it works

```sh
docker compose ps        # postgres and selenium "healthy", prefill "exited (0)", bot "healthy"
docker compose logs -f bot
```

A cycle takes one to three minutes. It ends with a line like
`Next run scheduled for 2026-10-13 11:00:00`. By then the first messages
should be in your channel. The bot shows `health: starting` until the first
step of that cycle finishes, then `healthy`. It turns `unhealthy` if it makes
no progress for the run interval plus 15 minutes.

`docker compose stop` and `docker compose down` let the bot finish the item
it is posting before it exits, so nothing is posted twice after a restart.
Items it did not reach are posted after the next start.

### Everyday commands

| Task | Command |
| --- | --- |
| Follow the bot's log | `docker compose logs -f bot` |
| Stop everything (data is kept) | `docker compose down` |
| Start again | `docker compose up -d` |
| Restart only the bot | `docker compose restart bot` |
| Update to the latest code | `git pull && docker compose up -d --build` (a server [updates itself](docs/deployment.md)) |
| Open a database shell | `docker compose exec postgres psql -U notam` |
| Back up the database | `docker compose exec postgres pg_dump -U notam notam > backup.sql` |
| Restore a backup into an empty database | `docker compose exec -T postgres psql -U notam notam < backup.sql` |

If you changed `POSTGRES_USER` or `POSTGRES_DB`, use your values instead of
`notam` in the commands above.

Data lives in named Docker volumes:

| Volume | Contents |
| --- | --- |
| `postgres` | The database |
| `maps` | Rendered NOTAM map images |
| `logs` | `notam.log`, overwritten on every start; use `docker compose logs` for history |
| `cartopy` | Natural Earth map data, downloaded on the first render |

To start over with an empty database, run `docker compose down -v`. **This
deletes all volumes.** The next start prefills COMPASS, the Federal
Register, Regulations.gov, SEC EDGAR and the USCG BNM feeds again and re-posts everything that is currently active.

### Troubleshooting

- **`required variable POSTGRES_PASSWORD is missing a value`**: set
  `POSTGRES_PASSWORD` in `.env`.
- **`bot` never starts and `prefill` exited with code 1**: check
  `docker compose logs prefill`. The usual cause is that the COMPASS site
  or the Federal Register, Regulations.gov or SEC EDGAR API or a USCG BNM
  feed could not be reached (or `REGULATIONS_GOV_API_KEY` is wrong, or SEC rejected
  `SEC_USER_AGENT`). Run
  `docker compose up -d` again once they are reachable.
- **`Unauthorized` in the bot log**: the token in `TELEGRAM_BOT_TOKEN` is
  wrong.
- **`Forbidden` or `chat not found` in the bot log**: the bot is not an admin
  of the channel, or `TELEGRAM_CHANNEL_ID` is wrong.
- **`password authentication failed`**: `POSTGRES_PASSWORD` was changed after
  the database was created (see step 2).
- **Changed `.env`?** Run `docker compose up -d` so the containers are
  recreated with the new values. `restart` keeps the old ones.

## Running without Docker

Requirements: Python 3.12+ and Google Chrome. The NOTAM search, FCC ELS and
FAA DRS scrapers drive a headless Chrome through Selenium.

```sh
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -e .                  # or ".[lock]" for the fully pinned environment
cp .env.example .env              # then fill in TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID
```

Set `RUN_MODE=standalone` in `.env` so Selenium launches your local Chrome
(the default, `docker`, expects the Selenium container). Then:

```sh
python prefill_compass.py          # once, so the existing COMPASS files are not announced
python prefill_federal_register.py # once, so the existing Federal Register documents are not announced
python prefill_regulations_gov.py  # once (with REGULATIONS_GOV_API_KEY set), likewise for Regulations.gov
python prefill_sec_edgar.py        # once (with SEC_USER_AGENT set), likewise for SpaceX's SEC filings
python prefill_uscg_bnm.py         # once, likewise for the Coast Guard notices to mariners
python -m src                      # or: python main.py, or: starship-notam
```

### Database

By default the bot uses a SQLite file (`NOTAM_DB_PATH`, default `notams.db`).
To use PostgreSQL instead, install the extra and set `DATABASE_URL` in `.env`:

```sh
pip install -e ".[postgres]"
```

```sh
DATABASE_URL=postgresql://notam:secret@localhost:5432/notam
```

The tables are created on startup. Data is not copied from an existing
SQLite file.

## Tests

```sh
pip install -e ".[dev]"
pytest
```

The tests read [`.env.test`](.env.test) instead of `.env`, so they never see
your real token or database. To run a script against the test settings, set
`NOTAM_ENV_FILE`; it then uses `test_notams.db`. Also set `NOTAM_LOG_DIR` so
the bot's own `logs/notam.log` is left alone:

```sh
NOTAM_ENV_FILE=.env.test NOTAM_LOG_DIR=logs/test python prefill_federal_register.py
```

The PostgreSQL tests in `tests/unit/test_data/test_postgres.py` are skipped
unless `TEST_DATABASE_URL` points at a disposable PostgreSQL database. They
drop and recreate the bot's tables. CI runs them against a PostgreSQL service.

## Project layout

```text
src/
  core/           configuration (.env) and logging
  scrapers/       fetch raw data from each source
  parsers/        turn raw HTML/JSON/NOTAM text into dicts
  data/           database schema (SQLite/PostgreSQL) and one repository per source
  visualization/  map rendering and NOTAM card images
  bot/            message formatting, Telegram transport, main loop
tests/            unit and integration tests (pytest + Hypothesis)
```

`bot/orchestrator/` is the only package that ties the layers together. The
layer boundaries are checked by `tests/integration/test_dependency_boundaries.py`.

## Contributing

Ideas and problems go in [issues](https://github.com/sanitaravel/starship_notam/issues/new/choose).
Use the feature request or bug report form.

All code changes go through pull requests:

1. Branch off `development` (e.g. `feat/...`, `fix/...`) and open a pull
   request into `development`. Run `pytest` locally before opening it. CI
   does not run on pull requests into `development`, but you can start it for
   any branch from the Actions tab (**CI → Run workflow**).
2. To release, open a pull request from `development` into `main`. `main`
   accepts pull requests **only from `development`**: the `source-branch`
   check fails for any other branch. The `tests` check must also pass. Merge
   it with a merge commit (squash and rebase are disabled on `main`) so the
   two branches keep the same history.

Direct pushes, force pushes and deletion are blocked on both `main` and
`development`.
