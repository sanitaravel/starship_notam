#!/usr/bin/env bash
# Deploy the latest release of the Starship NOTAM bot (origin/main).
#
# The systemd timer runs this every 5 minutes; see docs/deployment.md.
#
#   deploy/deploy.sh               deploy origin/main if it moved and CI published its image
#   deploy/deploy.sh --to <commit> deploy a specific commit, then hold it
#   deploy/deploy.sh --rollback    go back to the previously deployed commit, then hold it
#   deploy/deploy.sh --status      show what is deployed
#
# A deploy: back up the database, check out the commit (so compose.yaml
# matches the image), pull the image CI built for it, recreate the stack and
# wait for the bot to turn healthy. If it does not, the previous commit is
# redeployed and the failed one is skipped until a newer commit lands on main.
#
# State lives in deploy/.state/: current, previous, skip (a commit the timer
# must not deploy) and the lock file.

set -euo pipefail

IMAGE=ghcr.io/sanitaravel/starship-notam
# Seconds to wait for the bot to turn healthy, and between checks.
HEALTH_TIMEOUT=${NOTAM_HEALTH_TIMEOUT:-900}
HEALTH_POLL=${NOTAM_HEALTH_POLL:-15}
KEEP_BACKUPS=10

cd "$(dirname "$0")/.."
STATE=deploy/.state
BACKUPS=backups
mkdir -p "$STATE" "$BACKUPS"

log() { printf '%s\n' "$*"; }

exec 9>"$STATE/lock"
if ! flock -n 9; then
    log "Another deploy is running; skipping"
    exit 0
fi

state() { cat "$STATE/$1" 2>/dev/null || true; }
set_state() { printf '%s\n' "$2" >"$STATE/$1"; }
clear_state() { rm -f "$STATE/$1"; }
short() { printf '%s' "${1:0:12}"; }

# docker compose with the image of commit $1.
compose() {
    local commit=$1
    shift
    NOTAM_IMAGE_TAG="sha-$commit" docker compose "$@"
}

# Major version of the postgres image in compose.yaml at commit $1.
postgres_major() {
    git show "$1:compose.yaml" | sed -n 's/^ *image: *postgres:\([0-9]*\).*/\1/p' | head -n 1
}

backup_database() {
    local name=$1
    if [ -z "$(docker compose ps --status running -q postgres)" ]; then
        log "PostgreSQL is not running; no backup taken"
        return 0
    fi
    local file="$BACKUPS/pre-$name.sql.gz"
    log "Backing up the database to $file"
    docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' \
        | gzip >"$file.tmp" || return 1
    mv "$file.tmp" "$file"
    # Keep only the newest backups.
    ls -1t "$BACKUPS"/pre-*.sql.gz | tail -n +$((KEEP_BACKUPS + 1)) | xargs -r rm --
}

# Check out commit $1 and run its image. Returns non-zero on any failure.
switch_to() {
    local commit=$1
    log "Switching to $(short "$commit")"
    git -c advice.detachedHead=false checkout -q --detach "$commit" || return 1
    compose "$commit" pull --quiet || return 1
    compose "$commit" up -d --no-build --remove-orphans || return 1
}

# Wait until the bot container of commit $1 is healthy.
wait_healthy() {
    local commit=$1 deadline=$((SECONDS + HEALTH_TIMEOUT)) id status=unknown
    log "Waiting up to ${HEALTH_TIMEOUT}s for the bot to turn healthy"
    while [ "$SECONDS" -lt "$deadline" ]; do
        id=$(compose "$commit" ps -q bot)
        status=$(docker inspect -f '{{.State.Health.Status}}' "$id" 2>/dev/null || echo missing)
        case $status in
            healthy) return 0 ;;
            unhealthy) log "The bot is unhealthy"; return 1 ;;
        esac
        sleep "$HEALTH_POLL"
    done
    log "The bot did not turn healthy in time (last status: $status)"
    return 1
}

# Remove images of releases other than the current and previous one.
prune_images() {
    local keep_current keep_previous
    keep_current="sha-$(state current)"
    keep_previous="sha-$(state previous)"
    docker images "$IMAGE" --format '{{.Tag}}' \
        | grep '^sha-' \
        | grep -vx -e "$keep_current" -e "$keep_previous" \
        | sed "s|^|$IMAGE:|" \
        | xargs -r docker rmi >/dev/null 2>&1 || true
    docker image prune -f >/dev/null 2>&1 || true
}

# Deploy commit $1; roll back to the current one if it does not turn healthy.
deploy() {
    local target=$1 current
    current=$(state current)

    if [ -n "$current" ] && [ "$(postgres_major "$current")" != "$(postgres_major "$target")" ]; then
        log "ERROR: $(short "$target") changes the PostgreSQL major version" \
            "($(postgres_major "$current") -> $(postgres_major "$target"))."
        log "That needs a manual dump and restore; see docs/deployment.md. Skipping this commit."
        set_state skip "$target"
        return 1
    fi

    backup_database "$(short "$target")" || {
        log "ERROR: database backup failed; not deploying"
        return 1
    }

    if switch_to "$target" && wait_healthy "$target"; then
        if [ -n "$current" ] && [ "$current" != "$target" ]; then
            set_state previous "$current"
        fi
        set_state current "$target"
        log "Deployed $(short "$target")"
        prune_images
        return 0
    fi

    log "ERROR: deploying $(short "$target") failed; it will be skipped until a newer commit lands on main"
    set_state skip "$target"
    if [ -z "$current" ]; then
        log "ERROR: no earlier deploy to roll back to"
        return 1
    fi
    log "Rolling back to $(short "$current")"
    if switch_to "$current" && wait_healthy "$current"; then
        log "Rolled back to $(short "$current")"
    else
        log "ERROR: the rollback to $(short "$current") is not healthy either; check docker compose logs bot"
    fi
    return 1
}

image_exists() {
    local output
    if output=$(docker manifest inspect "$IMAGE:sha-$1" 2>&1 >/dev/null); then
        return 0
    fi
    log "No image for $(short "$1") yet ($(printf '%s' "$output" | head -n 1)); will retry"
    return 1
}

fetch() { git fetch -q origin main; }

if [ "${1:-}" != --status ]; then
    if [ ! -f .env ]; then
        log "ERROR: .env is missing; see docs/deployment.md"
        exit 1
    fi
    # A checkout would fail half-way, or silently drop edits made on the server.
    if ! git diff --quiet HEAD; then
        log "ERROR: tracked files were changed on the server; commit or discard them first:"
        git status --short --untracked-files=no
        exit 1
    fi
fi

case ${1:-} in
    "")
        fetch
        target=$(git rev-parse origin/main)
        if [ "$target" = "$(state current)" ] || [ "$target" = "$(state skip)" ]; then
            exit 0
        fi
        image_exists "$target" || exit 0
        log "New release on main: $(short "$target")"
        deploy "$target"
        ;;
    --to)
        [ -n "${2:-}" ] || { log "Usage: $0 --to <commit>"; exit 2; }
        fetch
        target=$(git rev-parse --verify "$2^{commit}")
        image_exists "$target" || exit 1
        deploy "$target"
        # Hold this commit: the timer resumes with the next commit on main.
        set_state skip "$(git rev-parse origin/main)"
        log "Holding $(short "$target"); automatic deploys resume with the next commit on main"
        ;;
    --rollback)
        previous=$(state previous)
        [ -n "$previous" ] || { log "No previous deploy recorded"; exit 1; }
        fetch
        deploy "$previous"
        set_state skip "$(git rev-parse origin/main)"
        log "Holding $(short "$previous"); automatic deploys resume with the next commit on main"
        ;;
    --status)
        git fetch -q origin main 2>/dev/null || log "(could not fetch origin)"
        printf 'current:   %s\nprevious:  %s\nskip:      %s\norigin/main: %s\n' \
            "$(state current)" "$(state previous)" "$(state skip)" \
            "$(git rev-parse origin/main 2>/dev/null)"
        ;;
    *)
        log "Unknown option: $1"
        exit 2
        ;;
esac
