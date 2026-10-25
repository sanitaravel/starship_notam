# Deploying to a server

How the bot runs on a Linux server and updates itself. Every release merged
into `main` is live within about 10 minutes, with no SSH needed. The design
and its reasons are in [deployment-plan.md](deployment-plan.md).

## How it works

```
PR development → main
        │
        ▼
GitHub Actions on main:  tests ──► publish ──► ghcr.io/sanitaravel/starship-notam:sha-<commit>
                                                        │
Server, every 5 min:  deploy/deploy.sh                  │
  origin/main moved? ─► image for it published? ─► back up database
  ─► check out the commit ─► pull its image ─► recreate the stack
  ─► bot healthy?  yes: done
                   no:  roll back to the previous release, skip this one
```

- **Only tested code is deployed.** CI publishes the image only after the
  tests pass on `main`. The server waits until the image for the new commit
  exists.
- **The server pulls; GitHub never connects to it.** No open port, no SSH key
  and no bot token on GitHub.
- **Nothing is posted twice.** A deploy stops the bot with SIGTERM; the bot
  finishes the item it is posting and exits. Items it did not reach are
  posted after the restart.
- **A broken release is rolled back automatically.** The new bot must turn
  `healthy` within 15 minutes (it reports progress after every step of a
  cycle). Otherwise the previous release is started again and the broken
  commit is skipped until a newer one lands on `main`.
- **The database is never deleted by an update.** It lives in the Docker
  volume `starship_notam_postgres`, which survives every container and image
  change. A compressed `pg_dump` is taken before each deploy into `backups/`
  (the newest 10 are kept).

## One-time server setup

Requirements: a Linux x86_64 server with systemd, about 2 GB of free RAM, and
the Telegram bot and channel and/or the Discord webhook from the
[README](../README.md#1-prerequisites).

1. **Install Docker Engine with the Compose plugin**
   ([instructions](https://docs.docker.com/engine/install/)), then check:

   ```sh
   docker compose version     # v2.x
   ```

2. **Create a user for the bot** and give it access to Docker:

   ```sh
   sudo useradd --system --create-home --shell /bin/bash notam
   sudo usermod -aG docker notam
   ```

   Members of the `docker` group are effectively root on the host. Use this
   user only for the bot.

3. **Clone the repository** to `/opt/starship_notam` (the systemd unit
   expects this path):

   ```sh
   sudo git clone https://github.com/sanitaravel/starship_notam.git /opt/starship_notam
   sudo chown -R notam:notam /opt/starship_notam
   ```

4. **Create `.env`** as the `notam` user and fill in `TELEGRAM_BOT_TOKEN` and
   `TELEGRAM_CHANNEL_ID` and/or `DISCORD_WEBHOOK_URL`, and `POSTGRES_PASSWORD` (see
   [README, step 2](../README.md#2-get-the-code-and-configure-it)):

   ```sh
   sudo -iu notam
   cd /opt/starship_notam
   cp .env.example .env
   chmod 600 .env
   nano .env
   exit
   ```

5. **Install and start the deploy timer:**

   ```sh
   sudo cp /opt/starship_notam/deploy/starship-notam-deploy.{service,timer} /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now starship-notam-deploy.timer
   ```

6. **Watch the first deploy:**

   ```sh
   journalctl -fu starship-notam-deploy
   ```

   Within about two minutes it pulls the images, starts PostgreSQL and
   Selenium, runs the prefill and starts the bot. It ends with
   `Deployed <commit>`.

> **The first start posts everything that is currently active** (NOTAMs,
> advisories, closures, licence filings), because the database is new. See
> [README, step 3](../README.md#3-start-the-bot).

## Everyday use

Run these on the server as the `notam` user, from `/opt/starship_notam`
(`sudo -iu notam`, then `cd /opt/starship_notam`).

| Task | Command |
| --- | --- |
| What is deployed | `deploy/deploy.sh --status` |
| Deploy log | `journalctl -u starship-notam-deploy` (add `-f` to follow) |
| Bot log | `docker compose logs -f bot` |
| Container status | `docker compose ps` (bot should be `healthy`) |
| Deploy now instead of waiting | `sudo systemctl start starship-notam-deploy` |
| Go back to the previous release | `deploy/deploy.sh --rollback` |
| Run a specific commit | `deploy/deploy.sh --to <commit>` |
| Pause automatic deploys | `sudo systemctl stop starship-notam-deploy.timer` |
| Resume automatic deploys | `sudo systemctl start starship-notam-deploy.timer` |

`--rollback` and `--to` **hold** the chosen release: the timer leaves it
running until a newer commit lands on `main`, then deploys that as usual.

### Things not to do on the server

- **Don't run `docker compose up` or `docker compose pull` by hand.** Without
  the tag the deploy script sets, Compose uses the `main` image, which may
  not be the release that is deployed. Use `deploy/deploy.sh --to <commit>`
  instead. `docker compose restart bot`, `logs`, `ps` and `exec` are fine.
- **Don't use `docker compose up --build`.** The server runs the images CI
  built and tested.
- **Don't edit tracked files** (such as `compose.yaml`). The deploy script
  refuses to run while there are local changes. Settings go in `.env`, which
  is not tracked.
- **Never run `docker compose down -v`** unless you mean to delete the
  database. `-v` removes the volumes.

## When something goes wrong

**A release was rolled back.** The deploy log shows why
(`The bot is unhealthy` or `did not turn healthy in time`). Look at the
failed bot's output in `docker compose logs bot`, fix it on `development` and
release again. The broken commit is skipped until then.

**The log says `No image for <commit> yet` for more than 15 minutes.**
- The CI run on `main` failed or is still running: check the Actions tab.
- The message ends in `unauthorized` or `denied`: the GHCR package is
  private. Make it public under GitHub → Packages →
  `starship-notam` → Package settings → Change visibility.

**`tracked files were changed on the server`.** Run `git status` and
`git diff`, then `git checkout -- <file>` to discard the change, or move the
setting to `.env`.

**`database backup failed`.** Nothing was changed. Check that PostgreSQL is
running (`docker compose ps postgres`) and that the disk is not full
(`df -h`).

## Restoring a backup

Backups are in `/opt/starship_notam/backups/pre-<commit>.sql.gz`, named after
the release that was deployed right after them.

```sh
sudo systemctl stop starship-notam-deploy.timer
docker compose stop bot
docker compose exec -T postgres sh -c 'dropdb -U "$POSTGRES_USER" "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
gunzip -c backups/pre-<commit>.sql.gz | docker compose exec -T postgres sh -c 'psql -q -U "$POSTGRES_USER" "$POSTGRES_DB"'
docker compose start bot
sudo systemctl start starship-notam-deploy.timer
```

## Rules for releases

These keep automatic deploys and rollbacks safe:

- **Database changes are additive only.** Add tables and columns
  (`CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ... ADD COLUMN` in
  `data/connection.py`); never drop or rename them in the same release that
  stops using them. Then the previous release still runs on the new schema,
  and a rollback is safe.
- **PostgreSQL major upgrades are manual.** A new major version cannot start
  on the old data files. The deploy script refuses a commit that changes the
  major version in `compose.yaml` and skips it. To upgrade to that commit:

  ```sh
  sudo systemctl stop starship-notam-deploy.timer
  docker compose stop bot
  docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > backups/pg-upgrade.sql.gz
  docker compose down                        # no -v: keeps logs, maps, cartopy
  docker volume rm starship_notam_postgres   # the old-version data files
  git fetch origin && git checkout --detach <commit>
  docker compose up -d --wait postgres       # new version, empty database
  gunzip -c backups/pg-upgrade.sql.gz | docker compose exec -T postgres sh -c 'psql -q -U "$POSTGRES_USER" "$POSTGRES_DB"'
  rm deploy/.state/current                   # lets the deploy script accept the new version
  deploy/deploy.sh --to <commit>
  sudo systemctl start starship-notam-deploy.timer
  ```

  Restore before the bot starts: on an empty database it would post
  everything that is currently active again.
- **New required settings go in `.env` on the server first**, before the
  release that needs them is merged into `main`.
