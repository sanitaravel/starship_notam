"""Tests for the per-source step scheduler."""

from __future__ import annotations

from src.bot.orchestrator.schedule import StepScheduler


def _make(tick: float):
    t = [0.0]
    return StepScheduler(tick, clock=lambda: t[0]), t


def test_never_run_source_is_due():
    s, _ = _make(5)
    assert s.due("x", 30)


def test_not_due_right_after_running():
    s, t = _make(5)
    s.mark_ran("x")
    t[0] += 5 * 60
    assert not s.due("x", 30)


def test_due_after_interval():
    s, t = _make(5)
    s.mark_ran("x")
    t[0] += 30 * 60
    assert s.due("x", 30)


def test_jitter_within_half_tick_counts_as_due():
    s, t = _make(5)
    s.mark_ran("x")
    t[0] += 29 * 60 + 57
    assert s.due("x", 30)


def test_well_short_of_interval_is_not_due():
    s, t = _make(5)
    s.mark_ran("x")
    t[0] += 27 * 60
    assert not s.due("x", 30)


def test_interval_below_tick_runs_every_cycle():
    s, t = _make(30)
    s.mark_ran("x")
    t[0] += 30 * 60
    assert s.due("x", 5)


def test_runs_per_hour_two_keeps_hourly_source_every_other_cycle():
    s, t = _make(30)
    assert s.due("x", 60)
    s.mark_ran("x")
    t[0] += 30 * 60
    assert not s.due("x", 60)
    t[0] += 30 * 60
    assert s.due("x", 60)


def test_overrun_runs_overdue_source_once():
    s, t = _make(5)
    s.mark_ran("x")
    t[0] += 17 * 60
    assert s.due("x", 10)
    s.mark_ran("x")
    t[0] += 5 * 60
    assert not s.due("x", 10)


def test_sources_are_tracked_independently():
    s, _ = _make(5)
    s.mark_ran("a")
    assert s.due("b", 30)
