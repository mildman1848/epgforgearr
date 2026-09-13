from __future__ import annotations

from datetime import datetime, timezone

import epgforgearr.workflow as workflow
from epgforgearr.workflow import generate_all_provider_sources, provider_profile, usable_provider_ids


class RecordingProvider:
    """Fake full provider recording programme fetch calls without network access."""

    def __init__(self, channels):
        self.calls: list[str] = []
        self._channels = channels

    def list_channels(self):
        return self._channels

    def fetch_programmes(self, provider_channel_id, days=1):
        self.calls.append(provider_channel_id)
        return [
            {
                "title": f"Programme {provider_channel_id}",
                "start": datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
                "stop": datetime(2026, 1, 1, 11, 0, tzinfo=timezone.utc),
            }
        ]


def test_provider_profile_matches_magenta_and_tvdigital_defaults():
    magenta = provider_profile("magenta")
    assert magenta["output_path"] == "/data/epgforgearr/magenta-full.xml"
    assert magenta["epg_source_name"] == "EPGForgearr: Magenta"
    assert magenta["epg_source_priority"] == 60

    tvdigital = provider_profile("tvdigital_de")
    assert tvdigital["output_path"] == "/data/epgforgearr/tvdigital-de-full.xml"
    assert tvdigital["epg_source_name"] == "EPGForgearr: TV Digital DE"
    assert tvdigital["epg_source_priority"] == 70


def test_provider_profile_derives_defaults_for_unknown_provider():
    # Any future usable provider without an explicit profile entry still gets
    # its own distinct output path/source name instead of colliding.
    profile = provider_profile("future_source")
    assert profile["output_path"] == "/data/epgforgearr/future-source-full.xml"
    assert profile["epg_source_name"] == "EPGForgearr: future_source"
    assert profile["epg_source_priority"] == workflow.DEFAULT_PROVIDER_PRIORITY


def test_usable_provider_ids_excludes_planned_simpli_tv():
    ids = usable_provider_ids()
    assert "magenta" in ids
    assert "tvdigital_de" in ids
    assert "simpli_tv" not in ids


def _fake_profile_in(tmp_path):
    def profile(provider_id: str) -> dict:
        return {
            "output_path": str(tmp_path / f"{provider_id}-full.xml"),
            "epg_source_name": f"EPGForgearr: {provider_id}",
            "epg_source_priority": 60 if provider_id == "magenta" else 70,
        }

    return profile


def test_generate_all_provider_sources_generates_and_installs_each_usable_provider(tmp_path, monkeypatch):
    providers = {
        "magenta": RecordingProvider([{"contentId": "550", "name": "Sport 1"}]),
        "tvdigital_de": RecordingProvider([{"id": "37", "name": "Das Erste"}]),
    }
    installed_calls: list[dict] = []

    def fake_install(settings, logger=None):
        installed_calls.append(dict(settings))
        return {"status": "ok", "message": f"EPGSource created: {settings['epg_source_name']}"}

    monkeypatch.setattr(workflow, "install_epg_source", fake_install)
    monkeypatch.setattr(workflow, "provider_profile", _fake_profile_in(tmp_path))

    settings = {
        # A single-provider output_path must never leak into the per-provider outputs.
        "output_path": str(tmp_path / "unused.xml"),
        "days": 1,
        "gzip_output": False,
    }
    result = generate_all_provider_sources(settings, provider_factory=lambda pid: providers[pid])

    assert result["status"] == "ok"
    assert set(result["providers"].keys()) == {"magenta", "tvdigital_de"}
    assert "simpli_tv" not in result["providers"]
    assert (tmp_path / "magenta-full.xml").exists()
    assert (tmp_path / "tvdigital_de-full.xml").exists()
    assert len(installed_calls) == 2
    assert {c["epg_source_name"] for c in installed_calls} == {
        "EPGForgearr: magenta",
        "EPGForgearr: tvdigital_de",
    }


def test_generate_all_provider_sources_continues_after_one_provider_fails(tmp_path, monkeypatch):
    def provider_factory(provider_id):
        if provider_id == "magenta":
            raise RuntimeError("magenta upstream down")
        return RecordingProvider([{"id": "37", "name": "Das Erste"}])

    monkeypatch.setattr(workflow, "install_epg_source", lambda settings, logger=None: {"status": "ok", "message": "ok"})
    monkeypatch.setattr(workflow, "provider_profile", _fake_profile_in(tmp_path))

    result = generate_all_provider_sources({"days": 1, "gzip_output": False}, provider_factory=provider_factory)

    assert result["status"] == "warning"
    assert result["providers"]["magenta"]["status"] == "error"
    assert result["providers"]["tvdigital_de"]["status"] == "ok"
    assert "RuntimeError" in result["providers"]["magenta"]["message"]
