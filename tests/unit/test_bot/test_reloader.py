"""Unit tests for the bot self-restart / source-watcher (``bot.reloader``).

Covers:
    * snapshot_sources: fingerprints every .py file, skips __pycache__.
    * sources_changed: detects modified / added / removed files, and reports
      no change when the tree is untouched.
    * _restart_argv: reconstructs a sensible relaunch command for both the
      ``python -m starship_notam`` and console-script launch styles.
    * restart_process: calls os.execv with the computed argv, flushes streams,
      and propagates an OSError (logging then re-raising) on failure.

The os.execv call is always monkeypatched so the test process is never
actually replaced.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from starship_notam.bot import reloader


def _make_tree(root: Path) -> None:
    """Create a small fake package tree with a __pycache__ file to ignore."""
    (root / "pkg").mkdir()
    (root / "pkg" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (root / "pkg" / "b.py").write_text("y = 2\n", encoding="utf-8")
    cache = root / "pkg" / "__pycache__"
    cache.mkdir()
    (cache / "a.cpython-312.pyc").write_text("ignored", encoding="utf-8")


# ---------------------------------------------------------------------------
# snapshot_sources
# ---------------------------------------------------------------------------
def test_snapshot_includes_py_files_and_skips_pycache(tmp_path):
    _make_tree(tmp_path)
    snap = reloader.snapshot_sources(tmp_path)

    keys = {Path(p).name for p in snap}
    assert keys == {"a.py", "b.py"}
    # No __pycache__ artifacts.
    assert not any("__pycache__" in p for p in snap)
    # Each value is a (size, mtime_ns) fingerprint tuple.
    for fp in snap.values():
        assert isinstance(fp, tuple) and len(fp) == 2


def test_snapshot_default_root_scans_installed_package():
    """With no argument it scans the real package and finds this module."""
    snap = reloader.snapshot_sources()
    assert any(Path(p).name == "reloader.py" for p in snap)
    assert any(Path(p).name == "orchestrator.py" for p in snap)


# ---------------------------------------------------------------------------
# sources_changed
# ---------------------------------------------------------------------------
def test_sources_changed_false_when_untouched(tmp_path):
    _make_tree(tmp_path)
    snap = reloader.snapshot_sources(tmp_path)
    assert reloader.sources_changed(snap, tmp_path) is False


def test_sources_changed_true_on_modification(tmp_path):
    _make_tree(tmp_path)
    snap = reloader.snapshot_sources(tmp_path)

    target = tmp_path / "pkg" / "a.py"
    # Change size *and* mtime so the fingerprint differs regardless of clock
    # resolution.
    target.write_text("x = 1  # updated\n", encoding="utf-8")
    import os, time
    future = time.time() + 10
    os.utime(target, (future, future))

    assert reloader.sources_changed(snap, tmp_path) is True


def test_sources_changed_true_on_added_file(tmp_path):
    _make_tree(tmp_path)
    snap = reloader.snapshot_sources(tmp_path)
    (tmp_path / "pkg" / "c.py").write_text("z = 3\n", encoding="utf-8")
    assert reloader.sources_changed(snap, tmp_path) is True


def test_sources_changed_true_on_removed_file(tmp_path):
    _make_tree(tmp_path)
    snap = reloader.snapshot_sources(tmp_path)
    (tmp_path / "pkg" / "b.py").unlink()
    assert reloader.sources_changed(snap, tmp_path) is True


# ---------------------------------------------------------------------------
# _restart_argv
# ---------------------------------------------------------------------------
def test_restart_argv_for_module_launch(monkeypatch):
    """When launched via ``python -m starship_notam`` (__package__ set)."""
    fake_main = types.ModuleType("__main__")
    fake_main.__package__ = "starship_notam"
    monkeypatch.setitem(sys.modules, "__main__", fake_main)
    monkeypatch.setattr(sys, "argv", ["/x/__main__.py", "--flag"])
    monkeypatch.setattr(sys, "executable", "/usr/bin/python3")

    argv = reloader._restart_argv()
    assert argv == ["/usr/bin/python3", "-m", "starship_notam", "--flag"]


def test_restart_argv_for_script_launch(monkeypatch):
    """When launched as a console script (no __package__)."""
    fake_main = types.ModuleType("__main__")
    fake_main.__package__ = ""
    monkeypatch.setitem(sys.modules, "__main__", fake_main)
    monkeypatch.setattr(sys, "argv", ["/usr/bin/starship-notam", "--flag"])
    monkeypatch.setattr(sys, "executable", "/usr/bin/python3")

    argv = reloader._restart_argv()
    assert argv == ["/usr/bin/python3", "/usr/bin/starship-notam", "--flag"]


# ---------------------------------------------------------------------------
# restart_process
# ---------------------------------------------------------------------------
def test_restart_process_calls_execv_with_computed_argv(monkeypatch):
    calls = {}

    monkeypatch.setattr(reloader, "_restart_argv",
                        lambda: ["/py", "-m", "starship_notam"])

    def fake_execv(path, argv):
        calls["path"] = path
        calls["argv"] = argv

    monkeypatch.setattr(reloader.os, "execv", fake_execv)

    reloader.restart_process()

    assert calls["path"] == "/py"
    assert calls["argv"] == ["/py", "-m", "starship_notam"]


def test_restart_process_reraises_on_execv_failure(monkeypatch):
    monkeypatch.setattr(reloader, "_restart_argv", lambda: ["/py", "-m", "starship_notam"])

    def boom(path, argv):
        raise OSError("exec failed")

    monkeypatch.setattr(reloader.os, "execv", boom)

    with pytest.raises(OSError):
        reloader.restart_process()
