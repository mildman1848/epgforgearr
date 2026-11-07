from __future__ import annotations

# `plugin.py` falls back to absolute imports when there is no parent package
# (see its top-level try/except), so it can be imported standalone here
# without Django or the Dispatcharr plugin loader.
import plugin


def test_scheduled_job_records_per_provider_results_and_advances_last_refresh(tmp_path, monkeypatch):
    settings = {"schedule_enabled": True, "data_dir": str(tmp_path / "data")}
    monkeypatch.setattr(plugin, "_load_settings", lambda: settings)
    monkeypatch.setattr(plugin, "_load_state", lambda _settings: {})
    saved_state: dict = {}
    monkeypatch.setattr(plugin, "_save_state", lambda _settings, state: saved_state.update(state))

    def fake_generate_all(_settings):
        return {
            "status": "ok",
            "message": "generated 2/2 provider EPG source(s), 0 failed",
            "providers": {
                "magenta": {"status": "ok", "message": "ok: magenta"},
                "tvdigital_de": {"status": "ok", "message": "ok: tvdigital_de"},
            },
            "provider_ids": ["magenta", "tvdigital_de"],
        }

    monkeypatch.setattr(plugin, "generate_all_provider_sources", fake_generate_all)

    result = plugin._scheduled_job()

    assert result["status"] == "ok"
    assert saved_state["last_full_refresh_status"] == "ok"
    assert saved_state["last_full_refresh"] > 0
    assert set(saved_state["providers"].keys()) == {"magenta", "tvdigital_de"}
    assert saved_state["providers"]["magenta"]["status"] == "ok"


def test_scheduled_job_does_not_advance_last_refresh_when_all_providers_fail(tmp_path, monkeypatch):
    settings = {"schedule_enabled": True, "data_dir": str(tmp_path / "data")}
    monkeypatch.setattr(plugin, "_load_settings", lambda: settings)
    monkeypatch.setattr(plugin, "_load_state", lambda _settings: {})
    saved: dict = {}
    monkeypatch.setattr(plugin, "_save_state", lambda _settings, state: saved.update(state))

    def fake_generate_all(_settings):
        return {
            "status": "error",
            "message": "generated 0/2 provider EPG source(s), 2 failed",
            "providers": {
                "magenta": {"status": "error", "message": "boom"},
                "tvdigital_de": {"status": "error", "message": "boom"},
            },
            "provider_ids": ["magenta", "tvdigital_de"],
        }

    monkeypatch.setattr(plugin, "generate_all_provider_sources", fake_generate_all)

    result = plugin._scheduled_job()

    assert result["status"] == "error"
    # Total failure keeps last_full_refresh unset so the next poll tick retries soon.
    assert "last_full_refresh" not in saved
    assert saved["last_full_refresh_status"] == "error"
    assert saved["providers"]["magenta"]["status"] == "error"


def test_scheduled_job_respects_schedule_disabled(tmp_path, monkeypatch):
    settings = {"schedule_enabled": False, "data_dir": str(tmp_path / "data")}
    monkeypatch.setattr(plugin, "_load_settings", lambda: settings)
    result = plugin._scheduled_job()
    assert result == {"status": "ok", "message": "schedule disabled"}


def test_scheduled_job_skips_when_not_due_yet(tmp_path, monkeypatch):
    import time

    settings = {"schedule_enabled": True, "data_dir": str(tmp_path / "data")}
    monkeypatch.setattr(plugin, "_load_settings", lambda: settings)
    monkeypatch.setattr(plugin, "_load_state", lambda _settings: {"last_full_refresh": int(time.time())})
    result = plugin._scheduled_job()
    assert result == {"status": "ok", "message": "not due yet"}


def test_provider_health_uses_real_coverage_and_preserves_last_success():
    old = {
        "magenta": {
            "last_success_at": "2025-01-01T00:00:00Z",
            "coverage_window": {"start": "2025-01-01T02:00:00+00:00", "end": "2025-01-02T02:00:00+00:00"},
            "channel_count": 12,
            "programme_count": 240,
        },
        "tvdigital_de": {"status": "ok", "last_success_at": "2025-01-01T00:00:00Z"},
    }
    health = plugin._provider_health_results(
        {
            "magenta": {
                "status": "ok",
                "message": "ok",
                "generated": {
                    "error_count": 0,
                    "channel_count": 15,
                    "programme_count": 300,
                    "coverage_start": "2025-02-01T01:00:00+00:00",
                    "coverage_end": "2025-02-03T01:00:00+00:00",
                },
            }
        },
        old,
        1738368000,
    )
    succeeded = health["magenta"]
    assert health["tvdigital_de"]["observed_in_last_attempt"] is False
    assert succeeded["observed_in_last_attempt"] is True
    assert succeeded["coverage_window"] == {
        "start": "2025-02-01T01:00:00+00:00",
        "end": "2025-02-03T01:00:00+00:00",
    }
    assert succeeded["channel_count"] == 15
    assert succeeded["programme_count"] == 300
    assert succeeded["last_success_at"] == "2025-02-01T00:00:00Z"

    failed = plugin._provider_health_results(
        {
            "magenta": {
                "status": "error",
                "message": "request failed token=do-not-leak https://example.invalid/path?sig=do-not-leak-either",
                "generated": {"error_count": 1, "errors": [{"error": "token=do-not-leak"}]},
            }
        },
        {"magenta": succeeded},
        1738454400,
    )["magenta"]
    persisted = str(failed)
    assert "do-not-leak" not in persisted
    assert "https://" not in persisted
    assert failed["last_success_at"] == succeeded["last_success_at"]
    assert failed["coverage_window"] == succeeded["coverage_window"]
    assert failed["channel_count"] == succeeded["channel_count"]
    assert failed["programme_count"] == succeeded["programme_count"]
    assert failed["last_attempt_at"] == "2025-02-02T00:00:00Z"


def test_failed_scheduled_refresh_persists_sanitized_health_and_keeps_success(tmp_path, monkeypatch):
    settings = {"schedule_enabled": True, "data_dir": str(tmp_path / "data")}
    previous = {
        "last_full_refresh": 1,
        "providers": {
            "magenta": {
                "last_success_at": "2025-01-01T00:00:00Z",
                "coverage_window": {"start": "2025-01-01T01:00:00+00:00", "end": "2025-01-02T01:00:00+00:00"},
                "channel_count": 4,
                "programme_count": 80,
            }
        },
    }
    saved: dict = {}
    monkeypatch.setattr(plugin, "_load_settings", lambda: settings)
    monkeypatch.setattr(plugin, "_load_state", lambda _settings: dict(previous))
    monkeypatch.setattr(plugin, "_save_state", lambda _settings, state: saved.update(state))
    monkeypatch.setattr(plugin, "_job_lock", lambda _name: "test-lock")
    monkeypatch.setattr(plugin, "_release_job_lock", lambda _path: None)
    monkeypatch.setattr(
        plugin,
        "generate_all_provider_sources",
        lambda _settings: {
            "status": "error",
            "message": "refresh failed token=do-not-persist https://example.invalid/signed/path?sig=do-not-persist",
            "providers": {
                "magenta": {
                    "status": "error",
                    "message": "refresh failed token=do-not-persist https://example.invalid/signed/path?sig=do-not-persist",
                    "generated": {"error_count": 1, "errors": [{"error": "token=do-not-persist"}]},
                }
            },
        },
    )

    result = plugin._scheduled_job()

    assert result["status"] == "error"
    assert "do-not-persist" not in str(result)
    assert "https://" not in str(result)
    assert "do-not-persist" not in str(saved)
    assert "https://" not in str(saved)
    assert saved["last_full_refresh"] == previous["last_full_refresh"]
    assert saved["providers"]["magenta"]["last_success_at"] == "2025-01-01T00:00:00Z"
    assert saved["providers"]["magenta"]["programme_count"] == 80
