# Deployment plan

How a merge into `main` reaches the server automatically. Written October
2026, before the first server deployment. Each part below is one branch,
merged into `development`; the deployment goes live with the next release
pull request into `main`.

Status legend: `[ ]` to do, `[x]` done, `[?]` needs a decision first.

---

## Goals

1. A merge into `main` is running on the server within minutes, with no SSH.
2. Only code that passed CI is deployed, and the image that runs is the
   exact image CI built.
3. A deploy never separates a send from its "posted" mark: no double
   posts, no lost posts.
4. A broken release rolls back automatically; a manual rollback is one
   command.
5. The server needs no inbound access, and GitHub holds no server
   credentials and no bot token.
6. An update never touches the database.

## Current state

- **No CD.** `.github/workflows/ci.yml` only runs the tests on pull requests
  into `main` and on pushes to `main`. Updating is a manual
  `git pull && docker compose up -d --build` on the server.
- **The in-process reloader cannot work in Docker.** `bot/reloader.py`
  restarts the bot when `*.py` files under the package change on disk, but
  the code is copied into the image, so a `git pull` on the host never
  changes the files the container sees. A rebuild replaces the whole
  container instead.
- **Every restart is a hard kill.** The bot runs as PID 1 without a SIGTERM
  handler, so it ignores SIGTERM and Docker kills it after 10 s.
  `_post_pending` (`bot/orchestrator.py:262`) sends first and marks posted
  afterwards, so a kill between the two re-posts the item on the next start.
  Automatic deploys would make this frequent.
- **Container logs are unbounded.** The default `json-file` driver has no
  size limit.

## Target flow

```
PR development → main (tests required)
        │
        ▼
GitHub Actions, push to main:  tests ──► build ──► push ghcr.io/sanitaravel/starship-notam:sha-<commit>, :main
                                                              │
Server, systemd timer every 5 min                             │
  deploy.sh: git fetch ─► origin/main moved? ─► image sha-<commit> exists? ─► pg_dump backup
             ─► checkout commit ─► docker compose pull ─► up -d
             ─► wait for bot healthy ─► ok: record version
                                      └► fail: roll back to the previous commit
```

## Decisions

| Decision | Choice | Why |
| --- | --- | --- |
| Server | Linux, x86_64, systemd | Confirmed. CI builds `linux/amd64` only. |
| Push or pull | **Pull**: the server polls every 5 min | No SSH key or open port for GitHub; works behind NAT. A delay of up to 5 min is irrelevant for a bot that runs every 30 min. |
| Where the image is built | **CI, pushed to GHCR** | Build once, deploy the same artifact. Rollback is a tag switch; the server never compiles. The repo is public, so pulls need no login. |
| Watchtower | **No** | Only swaps images: cannot apply `compose.yaml` changes, back up, health-check or roll back, and is barely maintained. |
| Deploy gate | **Image `sha-<commit>` exists** | The publish job runs only after `tests` passes on `main`, so an existing image means a green CI run. |
| In-process reloader | **Removed** | Does not work in Docker; graceful shutdown (part 1) keeps its "restart only between cycles" guarantee. |
| Failure alerts | **Logs only** (journald) | Confirmed. No Telegram notification. |

---

## Part 1 — Safe restarts (`fix/graceful-shutdown`)

Useful on its own: any restart, manual or automatic, stops risking a double
post.

### 1.1 Handle SIGTERM in `main_loop` `[x]`

- **Where:** `bot/orchestrator.py` (`main_loop`, `sleep_until_next_run`,
  `generate_and_send`, `_post_pending`, `_process_notam_images`)
- **Change:** an `asyncio.Event` (`_stop`), set by `loop.add_signal_handler`
  for SIGTERM and SIGINT (not available on Windows, where standalone mode
  keeps the existing `KeyboardInterrupt` handling).
  - Stop requested while sleeping → `sleep_until_next_run` waits on the event
    and returns at once; the bot exits.
  - Stop requested during a cycle → the item being sent finishes (send and
    mark), the remaining items and steps are skipped and stay pending for the
    next start, then the bot exits.
  - A second signal cancels the loop immediately.
- **Why not finish the whole cycle:** each send is followed by a 5 s pause,
  so a cycle with many new items (always the first one) runs well past any
  reasonable grace period. Measured in a container with 44 pending items:
  243 s to finish the cycle, 5 s to finish the current item.
- **Test:** `tests/unit/test_bot/test_main_loop.py` (real SIGTERM tests run
  on Linux only).

### 1.2 Give the bot time to stop `[x]`

- **Where:** `compose.yaml`, `bot` service
- **Change:** `stop_grace_period: 5m` (covers one item with Telegram
  retries, or a NOTAM scrape that cannot be interrupted) and
  `init: true` (tini as PID 1: forwards signals, reaps zombies).

### 1.3 Remove the reloader `[x]`

- **Where:** delete `bot/reloader.py` and
  `tests/unit/test_bot/test_reloader.py`; remove the import and the
  snapshot/restart block in `main_loop`.

### 1.4 Heartbeat and healthcheck `[x]`

- **Where:** `starship_notam/healthcheck.py`, `bot/orchestrator.py`,
  `compose.yaml`
- **Change:** after every cycle (even one where some steps failed — the loop
  itself is alive), write the current Unix time to `/tmp/notam-heartbeat`.
  The `bot` service gets a `healthcheck` that fails when the file is older
  than `60 / RUNS_PER_HOUR` minutes + 10 minutes, with `start_period: 10m`
  so the first cycle (which runs at start-up) can finish.
- **Purpose:** the deploy script uses `healthy` to accept a new version. It
  catches a crash at start-up and a hung loop.
- **Check:** `python -m starship_notam.healthcheck` (standard library only,
  so it never loads the config or truncates the log).
- **Test:** `tests/unit/test_healthcheck.py`; heartbeat after a cycle in
  `test_main_loop.py`.

### 1.5 Show the running version `[x]`

- **Where:** `Dockerfile` (at the end, so a new commit keeps the dependency
  layer cached), `core/config.py` (`VERSION`), `main_loop`
- **Change:** `ARG GIT_SHA=dev`, `ENV NOTAM_VERSION=$GIT_SHA`, OCI labels
  `org.opencontainers.image.revision` and `org.opencontainers.image.source`
  (the latter links the GHCR package to the repo). Log
  `Starting Starship NOTAM bot <version>` at start-up.

---

## Part 2 — Publish the image from CI (`ci/publish-image`)

### 2.1 `publish` job `[ ]`

- **Where:** `.github/workflows/ci.yml`
- **Change:** a job with `needs: tests` and
  `if: github.event_name == 'push' && github.ref == 'refs/heads/main'`.
  Job-level `permissions: { contents: read, packages: write }`.
  Steps: `docker/setup-buildx-action`, `docker/login-action` (ghcr.io,
  `GITHUB_TOKEN`), `docker/metadata-action`, `docker/build-push-action` with
  `platforms: linux/amd64`, `build-args: GIT_SHA=${{ github.sha }}` and
  `cache-from/cache-to: type=gha`.
- **Tags:** `sha-<full commit sha>` (immutable; what gets deployed) and `main`
  (moving; for manual runs).

### 2.2 Pin actions to commit SHAs `[ ]`

- **Why:** the publish job can write packages; a moved tag on a third-party
  action must not be able to push an image.

### 2.3 Make the package public `[ ]`

- **Manual, once:** after the first publish, check that
  `ghcr.io/sanitaravel/starship-notam` is public (GitHub → Packages →
  settings), so the server pulls without credentials.

---

## Part 3 — Server-side deploy (`feat/auto-deploy`)

### 3.1 `compose.yaml` `[ ]`

- `name: starship-notam` at the top. Volume names are prefixed with the
  project name, which otherwise comes from the directory name; pinning it
  means a clone in another directory still finds the same database.
- In the `x-app` anchor:
  `image: ghcr.io/sanitaravel/starship-notam:${NOTAM_IMAGE_TAG:-main}`,
  keeping `build: .` so `docker compose up --build` still works locally.
- A `logging:` block on every service: `driver: json-file`,
  `max-size: 10m`, `max-file: "5"`.

### 3.2 `deploy/deploy.sh` `[ ]`

POSIX shell, run on the server from the repo root. State lives in
`deploy/.state/` (git-ignored): `current`, `previous`, `failed`.

1. **Lock:** `flock -n` so two runs never overlap.
2. **Check:** `git fetch origin main`. If `origin/main` equals `current`, or
   equals `failed`, exit quietly.
3. **Gate:** `docker manifest inspect ghcr.io/sanitaravel/starship-notam:sha-<new>`.
   Missing (CI still running or failed) → exit; the next run retries.
4. **Guard:** if the new commit changes the PostgreSQL **major** version in
   `compose.yaml`, refuse and log that the upgrade needs a manual
   dump/restore (a new major cannot start on the old data directory).
5. **Back up:** `docker compose exec -T postgres pg_dump -U <user> <db> | gzip >
   backups/pre-<sha>.sql.gz`; keep the last 10. Skipped on the very first
   deploy (no database yet).
6. **Switch:** `git checkout --detach <new>` (so `compose.yaml` matches the
   image), then `NOTAM_IMAGE_TAG=sha-<new> docker compose pull` and
   `NOTAM_IMAGE_TAG=sha-<new> docker compose up -d --remove-orphans`.
7. **Verify:** poll `docker inspect` until the `bot` container is `healthy`,
   for up to 12 minutes.
   - Healthy → `previous = current`, `current = <new>`, clear `failed`,
     `docker image prune -f` (images only).
   - Not healthy → check out `previous`, `up -d` with its tag, write `<new>`
     to `failed` so it is not retried every 5 minutes. The next commit on
     `main` replaces it.
8. **Log** every step to stdout (journald).

Manual use: `deploy.sh --rollback` (go back to `previous`) and
`deploy.sh --to <sha>` (deploy a specific commit that has an image).

The script never runs `docker compose down -v`, `docker volume rm` or
`docker system prune --volumes`.

### 3.3 systemd units `[ ]`

- `deploy/starship-notam-deploy.service`: `Type=oneshot`,
  `User=notam` (member of the `docker` group),
  `WorkingDirectory=/opt/starship-notam`, `ExecStart=.../deploy/deploy.sh`.
- `deploy/starship-notam-deploy.timer`: `OnBootSec=2min`,
  `OnUnitActiveSec=5min`, `Persistent=true`.

### 3.4 Documentation `[ ]`

- `docs/deployment.md`: one-time server setup, watching deploys, rollback,
  restoring a backup, and the database rules below.
- README: replace the "Update to the latest code" row with a link to it.

---

## Database safety

An update never deletes the database:

- PostgreSQL data lives in the named volume `postgres`
  (`/var/lib/postgresql/data`). Volumes are independent of containers and
  images; recreating `bot`, `prefill` or even `postgres` reattaches the same
  volume.
- Only `docker compose down -v`, `docker volume rm` or
  `docker system prune --volumes` delete it. The deploy script uses none of
  them.
- The project name is pinned (3.1), so a different clone directory does not
  silently start a new, empty volume (which would re-post everything active).
- A PostgreSQL major-version change is blocked by the deploy script (3.2,
  step 4).
- A `pg_dump` is taken before every deploy (3.2, step 5).
- **Rule for future code:** schema changes stay additive (`CREATE TABLE IF
  NOT EXISTS`, `ALTER TABLE ... ADD COLUMN`, as `data/connection.py` does
  today). Then the previous version still runs on a migrated database, and
  an automatic rollback is safe. Dropping or renaming a column needs two
  releases: stop using it, then remove it.

## One-time server setup (summary)

The bot is not deployed yet, so the first deploy starts from an empty
database.

1. Install Docker Engine with the Compose plugin.
2. Create a `notam` user in the `docker` group.
3. `git clone https://github.com/sanitaravel/starship_notam /opt/starship-notam`
4. `cp .env.example .env` and fill in `TELEGRAM_BOT_TOKEN`,
   `TELEGRAM_CHANNEL_ID`, `POSTGRES_PASSWORD`.
5. Copy the two units to `/etc/systemd/system/`, then
   `systemctl enable --now starship-notam-deploy.timer`.
6. Watch the first deploy: `journalctl -fu starship-notam-deploy`.

The first start prefills COMPASS and the Federal Register, then posts every
currently active NOTAM, advisory and closure once (see README, "Start the
bot").

## Out of scope

- **Migration tooling (Alembic):** not needed while schema changes stay
  additive.
- **Staging environment:** one bot and one channel; `development` plus the
  test suite cover this.
- **Zero-downtime deploys:** a gap of a minute or two between scheduled
  cycles costs nothing.
- **Failure notifications:** logs only, by decision.
