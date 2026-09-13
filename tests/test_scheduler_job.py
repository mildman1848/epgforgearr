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
