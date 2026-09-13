from __future__ import annotations

# `plugin.py` falls back to absolute imports when there is no parent package
# (see its top-level try/except), so it can be imported standalone here
# without Django or the Dispatcharr plugin loader.
from plugin import STATE_REFRESH_INTERVAL, compute_scheduler_status


def test_scheduler_status_never_run_is_due_immediately():
    status = compute_scheduler_status({"schedule_enabled": True}, {}, thread_alive=True, now=1_000_000)
    assert status["schedule_enabled"] is True
    assert status["thread_alive"] is True
    assert status["last_refresh"] is None
    assert status["next_due"] == 1_000_000
    assert status["seconds_until_due"] == 0


def test_scheduler_status_reports_seconds_until_due():
    now = 1_000_000
    last_refresh = now - 3600  # refreshed an hour ago
    state = {"last_full_refresh": last_refresh, "last_full_refresh_at": "2026-01-01 00:00:00", "last_full_refresh_status": "ok"}
    status = compute_scheduler_status({"schedule_enabled": True}, state, thread_alive=False, now=now)
    assert status["last_refresh"] == last_refresh
    assert status["last_refresh_at"] == "2026-01-01 00:00:00"
    assert status["last_refresh_status"] == "ok"
    assert status["next_due"] == last_refresh + STATE_REFRESH_INTERVAL
    assert status["seconds_until_due"] == STATE_REFRESH_INTERVAL - 3600
    assert status["thread_alive"] is False


def test_scheduler_status_overdue_clamps_seconds_until_due_to_zero():
    now = 1_000_000
    last_refresh = now - (STATE_REFRESH_INTERVAL * 2)  # long overdue
    status = compute_scheduler_status({"schedule_enabled": True}, {"last_full_refresh": last_refresh}, thread_alive=True, now=now)
    assert status["seconds_until_due"] == 0
    assert status["next_due"] < now


def test_scheduler_status_disabled_has_no_next_due():
    status = compute_scheduler_status({"schedule_enabled": False}, {"last_full_refresh": 1}, thread_alive=False, now=1_000_000)
    assert status["schedule_enabled"] is False
    assert status["next_due"] is None
    assert status["seconds_until_due"] is None


def test_scheduler_status_defaults_schedule_enabled_true_when_unset():
    status = compute_scheduler_status({}, {}, thread_alive=False, now=1_000_000)
    assert status["schedule_enabled"] is True
