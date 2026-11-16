from __future__ import annotations

from datetime import datetime, timezone

import pytest
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

    ewtn = provider_profile("ewtn_de")
    assert ewtn["output_path"] == "/data/epgforgearr/ewtn-de-full.xml"
    assert ewtn["epg_source_name"] == "EPGForgearr: EWTN Deutschland"

    bibeltv = provider_profile("bibeltv_impuls")
    assert bibeltv["output_path"] == "/data/epgforgearr/bibeltv-impuls-full.xml"
    assert bibeltv["epg_source_name"] == "EPGForgearr: Bibel TV Impuls"
    assert bibeltv["epg_source_priority"] == 85

    freeepg = provider_profile("freeepg_de")
    assert freeepg["output_path"] == "/data/epgforgearr/freeepg-de-full.xml"
    assert freeepg["epg_source_name"] == "EPGForgearr: FreeEPG Deutschland"

    freeepg_ch = provider_profile("freeepg_ch")
    assert freeepg_ch["output_path"] == "/data/epgforgearr/freeepg-ch-full.xml"
    assert freeepg_ch["epg_source_name"] == "EPGForgearr: FreeEPG Schweiz"
    assert freeepg_ch["epg_source_priority"] == 95


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
        "ewtn_de": RecordingProvider([{"id": "EWTN.de", "name": "EWTN Deutschland"}]),
        "bibeltv_impuls": RecordingProvider([{"id": "BibelTVImpuls.de", "name": "Bibel TV Impuls"}]),
        "freeepg_de": RecordingProvider([{"id": "ARD.de", "name": "Das Erste"}]),
        "freeepg_ch": RecordingProvider([{"id": "SRF1.ch", "name": "SRF 1"}]),
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
    assert set(result["providers"].keys()) == {"magenta", "tvdigital_de", "ewtn_de", "bibeltv_impuls", "freeepg_de", "freeepg_ch"}
    assert "simpli_tv" not in result["providers"]
    assert (tmp_path / "magenta-full.xml").exists()
    assert (tmp_path / "tvdigital_de-full.xml").exists()
    assert (tmp_path / "ewtn_de-full.xml").exists()
    assert (tmp_path / "bibeltv_impuls-full.xml").exists()
    assert (tmp_path / "freeepg_de-full.xml").exists()
    assert (tmp_path / "freeepg_ch-full.xml").exists()
    assert len(installed_calls) == 6
    assert {c["epg_source_name"] for c in installed_calls} == {
        "EPGForgearr: magenta",
        "EPGForgearr: tvdigital_de",
        "EPGForgearr: ewtn_de",
        "EPGForgearr: bibeltv_impuls",
        "EPGForgearr: freeepg_de",
        "EPGForgearr: freeepg_ch",
    }


def test_generate_all_provider_sources_can_generate_without_installing(tmp_path, monkeypatch):
    providers = {"magenta": RecordingProvider([{"id": "M1", "name": "Magenta One"}])}
    monkeypatch.setattr(workflow, "provider_profile", _fake_profile_in(tmp_path))
    monkeypatch.setattr(workflow, "install_epg_source", lambda *args, **kwargs: pytest.fail("install should not run"))
    result = generate_all_provider_sources(
        {"source_magenta": True, "source_tvdigital_de": False, "days": 1, "gzip_output": False},
        provider_factory=lambda pid: providers[pid], generate=True, install=False,
    )
    assert result["status"] == "ok"
    assert result["provider_ids"] == ["magenta"]
    assert result["providers"]["magenta"]["generated"]["status"] == "ok"
    assert "installed" not in result["providers"]["magenta"]


def test_generate_all_provider_sources_can_install_without_generating(tmp_path, monkeypatch):
    installed = []
    monkeypatch.setattr(workflow, "provider_profile", _fake_profile_in(tmp_path))
    monkeypatch.setattr(workflow, "generate_full_provider_epg", lambda *args, **kwargs: pytest.fail("generate should not run"))
    monkeypatch.setattr(workflow, "install_epg_source", lambda settings, logger=None: installed.append(settings["full_provider"]) or {"status": "ok", "message": "installed"})
    result = generate_all_provider_sources(
        {"source_magenta": False, "source_bibeltv_impuls": True}, generate=False, install=True,
    )
    assert result["status"] == "ok"
    assert installed == ["bibeltv_impuls"]


def test_generate_all_provider_sources_rejects_empty_selection():
    settings = {f"source_{provider_id}": False for provider_id in usable_provider_ids()}
    result = generate_all_provider_sources(settings)
    assert result["status"] == "error"
    assert result["provider_ids"] == []


def test_manifest_exposes_exactly_four_requested_actions():
    import json
    from pathlib import Path

    manifest = json.loads((Path(__file__).resolve().parents[1] / "plugin.json").read_text())
    assert [action["id"] for action in manifest["actions"]] == [
        "scan_missing_epg", "install_provider_sources", "generate_provider_epgs", "install_and_generate_provider_epgs"
    ]
    assert {field["id"] for field in manifest["fields"] if field["id"].startswith("source_")} == {
        f"source_{provider_id}" for provider_id in usable_provider_ids()
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
