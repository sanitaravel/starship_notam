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

### 2.1 `publish` job `[x]`

- **Where:** `.github/workflows/ci.yml`
- **Change:** a job with `needs: tests` and
  `if: github.event_name == 'push' && github.ref == 'refs/heads/main'`.
  Job-level `permissions: { contents: read, packages: write }`.
  Steps: `docker/setup-buildx-action`, `docker/login-action` (ghcr.io,
  `GITHUB_TOKEN`), `docker/metadata-action`, `docker/build-push-action` with
  `platforms: linux/amd64`, `build-args: GIT_SHA=${{ github.sha }}` and
  `cache-from/cache-to: type=gha`. It builds from the pushed commit (Git
  context), so there is no checkout step.
- **First real run:** the job only runs on `main`, so it is first exercised
  by the release that contains it. Check the Actions tab after that merge.
- **Tags:** `sha-<full commit sha>` (immutable; what gets deployed) and `main`
  (moving; for manual runs).

### 2.2 Pin actions to commit SHAs `[x]`

- **Why:** the publish job can write packages; a moved tag on a third-party
  action must not be able to push an image.
- **Pinned:** setup-buildx-action v4.4.1, login-action v4.6.0,
  metadata-action v6.2.0, build-push-action v7.4.0 (the release tag is in a
  comment next to each SHA; update both together).

### 2.3 Make the package public `[ ]`

- **Manual, once:** after the first publish, check that
  `ghcr.io/sanitaravel/starship-notam` is public (GitHub → Packages →
  settings), so the server pulls without credentials.

---

## Part 3 — Server-side deploy (`feat/auto-deploy`)

### 3.1 `compose.yaml` `[x]`

- `name: starship_notam` at the top. Volume names are prefixed with the
  project name, which otherwise comes from the directory name; pinning it
  means a clone in another directory still finds the same database. It
  matches the name a default clone (`starship_notam/`) already had, so
  existing local volumes keep working.
- In the `x-app` anchor:
  `image: ghcr.io/sanitaravel/starship-notam:${NOTAM_IMAGE_TAG:-main}`,
  keeping `build: .` so `docker compose up --build` still works locally.
- A `logging:` block on every service: `driver: json-file`,
  `max-size: 10m`, `max-file: "5"`.

### 3.2 `deploy/deploy.sh` `[x]`

Bash (for `pipefail`), run on the server from the repo root. State lives in
`deploy/.state/` (git-ignored): `current`, `previous`, `skip` (a commit the
timer must not deploy) and the lock file.

0. **Preconditions:** `.env` exists and no tracked file has local changes
   (a checkout would fail half-way or drop the edit).
1. **Lock:** `flock -n` so two runs never overlap.
2. **Check:** `git fetch origin main`. If `origin/main` equals `current` or
   `skip`, exit quietly.
3. **Gate:** `docker manifest inspect ghcr.io/sanitaravel/starship-notam:sha-<new>`.
   Missing (CI still running or failed, or the package is private) → log the
   reason and exit; the next run retries.
4. **Guard:** if the new commit changes the PostgreSQL **major** version in
   `compose.yaml`, refuse, skip the commit and point to the manual upgrade
   in `docs/deployment.md`.
5. **Back up:** `pg_dump` inside the postgres container, gzipped to
   `backups/pre-<commit>.sql.gz`; the newest 10 are kept. Skipped when
   PostgreSQL is not running (first deploy). A failed backup aborts the
   deploy.
6. **Switch:** `git checkout --detach <new>` (so `compose.yaml` matches the
   image), then `docker compose pull` and
   `docker compose up -d --no-build --remove-orphans`, both with
   `NOTAM_IMAGE_TAG=sha-<new>`.
7. **Verify:** poll `docker inspect` until the `bot` container is `healthy`,
   for up to 15 minutes.
   - Healthy → `previous = current`, `current = <new>`; remove images of
     other releases.
   - Not healthy → write `<new>` to `skip`, switch back to `current` and
     wait for it to turn healthy again. The next commit on `main` is
     deployed as usual.
8. **Log** every step to stdout (journald).

Manual use: `--rollback` (go back to `previous`), `--to <commit>` (deploy a
commit that has an image) and `--status`. `--rollback` and `--to` hold the
chosen release by writing the current `origin/main` to `skip`.

The script never runs `docker compose down -v`, `docker volume rm` or
`docker system prune --volumes`.

**Changed from the first draft:** the heartbeat is now also written after
every step of a cycle (`generate_and_send`), not only after a whole cycle.
The first cycle on a new database posts everything with a 5 s pause per
message and could outlast the health wait, which would roll back a working
release.

**Test:** `tests/deploy/test_deploy_script.py` runs the script against a
real git origin and a stub `docker` (Linux only; runs in CI).

### 3.3 systemd units `[x]`

- `deploy/starship-notam-deploy.service`: `Type=oneshot`,
  `User=notam` (member of the `docker` group),
  `WorkingDirectory=/opt/starship_notam`, `TimeoutStartSec=45min`.
- `deploy/starship-notam-deploy.timer`: `OnBootSec=2min`,
  `OnUnitActiveSec=5min`. (`Persistent=` from the first draft only applies
  to `OnCalendar=` timers, so it is not used.)
- `.gitattributes` keeps LF line endings for the script and units.

### 3.4 Documentation `[x]`

- `docs/deployment.md`: one-time server setup, everyday commands, what not
  to do on the server, troubleshooting, restoring a backup, PostgreSQL
  major upgrades and the release rules.
- README: links to it from the Docker section and the update command.

---

## Database safety

An update never deletes the database:

- PostgreSQL data lives in the named volume `starship_notam_postgres`
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

## One-time server setup

Step by step in [deployment.md](deployment.md#one-time-server-setup). The
bot is not deployed yet, so the first deploy starts from an empty database:
it prefills COMPASS and the Federal Register, then posts every currently
active NOTAM, advisory and closure once.

## Out of scope

- **Migration tooling (Alembic):** not needed while schema changes stay
  additive.
- **Staging environment:** one bot and one channel; `development` plus the
  test suite cover this.
- **Zero-downtime deploys:** a gap of a minute or two between scheduled
  cycles costs nothing.
- **Failure notifications:** logs only, by decision.
