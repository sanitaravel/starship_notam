"""deploy/deploy.sh against a real git origin and a stub ``docker`` command.

The stub records every call, reports an image as published when its tag is
listed in ``images``, and reports the bot's health from ``health/<tag>``
(healthy unless that file says otherwise). Linux only: the script needs bash,
flock and a POSIX shell environment.
"""

from __future__ import annotations

import gzip
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or not shutil.which("flock") or not shutil.which("git"),
    reason="needs Linux with bash, flock and git",
)

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "deploy.sh"

STUB_DOCKER = r"""#!/usr/bin/env bash
echo "${NOTAM_IMAGE_TAG:-} docker $*" >>"$STUB/calls"
case $1 in
    manifest)
        tag=${3##*:}
        grep -qx "$tag" "$STUB/images" 2>/dev/null && exit 0
        echo "manifest unknown" >&2
        exit 1 ;;
    inspect)
        cat "$STUB/health/$(cat "$STUB/running")" 2>/dev/null || echo healthy ;;
    compose)
        shift
        case $1 in
            ps)
                if [[ " $* " == *" postgres "* ]]; then
                    [ -f "$STUB/running" ] && echo pg-container
                else
                    echo bot-container
                fi ;;
            exec) echo "-- dump" ;;
            up) echo "$NOTAM_IMAGE_TAG" >"$STUB/running" ;;
        esac ;;
esac
exit 0
"""

COMPOSE = "services:\n  postgres:\n    image: postgres:{major}.1-bookworm\n"


GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


def git(cwd, *args):
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env={**os.environ, **GIT_IDENTITY},
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class Server:
    """An origin repo, a developer clone and the server's clone."""

    def __init__(self, root: Path):
        self.stub = root / "stub"
        (self.stub / "health").mkdir(parents=True)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        docker = bin_dir / "docker"
        docker.write_text(STUB_DOCKER)
        docker.chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "STUB": str(self.stub),
            "NOTAM_HEALTH_POLL": "0",
            "NOTAM_HEALTH_TIMEOUT": "5",
        }

        self.origin = root / "origin.git"
        git(root, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.dev = root / "dev"
        git(root, "clone", "-q", str(self.origin), str(self.dev))
        git(self.dev, "symbolic-ref", "HEAD", "refs/heads/main")
        (self.dev / "deploy").mkdir()
        shutil.copy(SCRIPT, self.dev / "deploy" / "deploy.sh")
        (self.dev / ".gitignore").write_text("deploy/.state/\nbackups/\n.env\n")
        self.first = self.commit("initial")

        self.dir = root / "server"
        git(root, "clone", "-q", str(self.origin), str(self.dir))
        (self.dir / ".env").write_text("POSTGRES_PASSWORD=x\n")

    def commit(self, message, *, postgres_major=17):
        (self.dev / "compose.yaml").write_text(COMPOSE.format(major=postgres_major))
        (self.dev / "release.txt").write_text(message)
        git(self.dev, "add", "-A")
        git(self.dev, "commit", "-q", "-m", message)
        git(self.dev, "push", "-q", "origin", "main")
        return git(self.dev, "rev-parse", "HEAD")

    def publish(self, commit):
        with open(self.stub / "images", "a") as f:
            f.write(f"sha-{commit}\n")

    def make_unhealthy(self, commit):
        (self.stub / "health" / f"sha-{commit}").write_text("unhealthy\n")

    def run(self, *args):
        (self.stub / "calls").unlink(missing_ok=True)
        return subprocess.run(
            ["bash", str(self.dir / "deploy" / "deploy.sh"), *args],
            env=self.env,
            capture_output=True,
            text=True,
        )

    def state(self, name):
        path = self.dir / "deploy" / ".state" / name
        return path.read_text().strip() if path.exists() else None

    def running(self):
        return (self.stub / "running").read_text().strip()

    def head(self):
        return git(self.dir, "rev-parse", "HEAD")

    def calls(self):
        path = self.stub / "calls"
        return path.read_text() if path.exists() else ""


@pytest.fixture
def server(tmp_path):
    return Server(tmp_path)


def deployed(server, commit):
    server.publish(commit)
    result = server.run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert server.state("current") == commit
    return result


def test_deploys_a_new_release(server):
    result = deployed(server, server.first)

    assert server.running() == f"sha-{server.first}"
    assert server.head() == server.first
    assert f"sha-{server.first} docker compose up -d --no-build --remove-orphans" in server.calls()
    assert "Deployed" in result.stdout


def test_waits_until_ci_published_the_image(server):
    result = server.run()

    assert result.returncode == 0
    assert "No image" in result.stdout
    assert "manifest unknown" in result.stdout
    assert "compose up" not in server.calls()
    assert server.state("current") is None


def test_no_new_release_is_a_quiet_no_op(server):
    deployed(server, server.first)

    result = server.run()

    assert result.returncode == 0
    assert result.stdout == ""
    assert "compose" not in server.calls()


def test_backs_up_the_database_before_switching(server):
    deployed(server, server.first)
    second = server.commit("second")

    deployed(server, second)

    backup = server.dir / "backups" / f"pre-{second[:12]}.sql.gz"
    assert gzip.decompress(backup.read_bytes()) == b"-- dump\n"
    calls = server.calls()
    assert calls.index("compose exec -T postgres") < calls.index("compose up")
    assert server.state("previous") == server.first


def test_unhealthy_release_is_rolled_back_and_skipped(server):
    deployed(server, server.first)
    bad = server.commit("bad")
    server.publish(bad)
    server.make_unhealthy(bad)

    result = server.run()

    assert result.returncode == 1
    assert "Rolled back" in result.stdout
    assert server.state("current") == server.first
    assert server.state("skip") == bad
    assert server.running() == f"sha-{server.first}"
    assert server.head() == server.first

    # The timer does not retry it...
    retry = server.run()
    assert retry.returncode == 0
    assert "compose up" not in server.calls()

    # ...but deploys the next commit on main.
    fixed = server.commit("fixed")
    deployed(server, fixed)
    assert server.state("previous") == server.first


def test_postgres_major_upgrade_is_refused(server):
    deployed(server, server.first)
    upgrade = server.commit("pg 18", postgres_major=18)
    server.publish(upgrade)

    result = server.run()

    assert result.returncode == 1
    assert "PostgreSQL major version (17 -> 18)" in result.stdout
    assert "compose up" not in server.calls()
    assert server.state("current") == server.first
    assert server.state("skip") == upgrade


def test_rollback_returns_to_the_previous_release_and_holds_it(server):
    deployed(server, server.first)
    second = server.commit("second")
    deployed(server, second)

    result = server.run("--rollback")

    assert result.returncode == 0, result.stdout
    assert server.state("current") == server.first
    assert server.running() == f"sha-{server.first}"
    assert server.state("skip") == second
    assert server.run().stdout == ""


def test_to_deploys_a_given_commit_and_holds_it(server):
    deployed(server, server.first)
    second = server.commit("second")
    deployed(server, second)

    result = server.run("--to", server.first[:10])

    assert result.returncode == 0, result.stdout
    assert server.state("current") == server.first
    assert server.state("skip") == second


def test_refuses_to_run_with_local_changes(server):
    (server.dir / "release.txt").write_text("edited on the server")

    result = server.run()

    assert result.returncode == 1
    assert "tracked files were changed" in result.stdout
    assert server.calls() == ""


def test_refuses_to_run_without_env_file(server):
    (server.dir / ".env").unlink()

    result = server.run()

    assert result.returncode == 1
    assert ".env is missing" in result.stdout


def test_a_running_deploy_blocks_a_second_one(server):
    import fcntl  # POSIX only, like the whole module

    state = server.dir / "deploy" / ".state"
    state.mkdir(parents=True)
    with open(state / "lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        result = server.run()

    assert result.returncode == 0
    assert "Another deploy is running" in result.stdout
    assert server.calls() == ""


def test_status_shows_the_deployed_commit(server):
    deployed(server, server.first)

    result = server.run("--status")

    assert f"current:   {server.first}" in result.stdout
    assert f"origin/main: {server.first}" in result.stdout
