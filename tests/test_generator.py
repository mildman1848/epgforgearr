from __future__ import annotations

import gzip
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from epgforgearr.generator import build_xmltv, generate_xmltv, parse_mapping_config, supported_sources
from epgforgearr.workflow import export_mapping_template, generate_full_provider_epg


class RecordingProvider:
    """Fake full provider recording programme fetch calls without network access."""

    def __init__(self, channels: list[dict[str, str]] | None = None):
        self.calls: list[str] = []
        self._channels = channels or []

    def list_channels(self):
        return self._channels

    def fetch_programmes(self, provider_channel_id: str, days: int = 1):
        self.calls.append(provider_channel_id)
        return [
            {
                "title": f"Full programme {provider_channel_id}",
                "start": datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
                "stop": datetime(2026, 1, 1, 11, 0, 0, tzinfo=timezone.utc),
            }
        ]


class FakeProvider:
    def fetch_programmes(self, provider_channel_id: str, days: int = 1):
        return [
            {
                "title": f"Programme for {provider_channel_id}",
                "subtitle": "Episode 1",
                "description": "Synthetic fixture programme.",
                "start": datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
                "stop": datetime(2026, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
            }
        ]


def test_supported_sources_lists_magenta():
    assert any(s["id"] == "magenta" for s in supported_sources())


def test_parse_mapping_config_validates_and_orders_sources():
    mappings = parse_mapping_config(json.dumps([
        {
            "channel_id": "DAZN.BAR1",
            "display_name": "DAZN 1 BAR",
            "sources": [
                {"provider": "magenta", "provider_channel_id": "5075", "label": "fallback", "priority": 20},
                {"provider": "magenta", "provider_channel_id": "550", "label": "primary", "priority": 1},
            ],
        }
    ]))
    assert mappings[0].channel_id == "DAZN.BAR1"
    assert [s.provider_channel_id for s in mappings[0].sources] == ["550", "5075"]


def test_build_xmltv_uses_first_successful_source():
    mappings = parse_mapping_config([
        {"channel_id": "kodiboxarr.MAGENTA SPORT 1", "display_name": "MAGENTA SPORT 1", "sources": [{"provider": "fake", "provider_channel_id": "550"}]}
    ])
    tree, report = build_xmltv(mappings, days=1, provider_factory=lambda _provider: FakeProvider())
    root = tree.getroot()
    assert report["channel_count"] == 1
    assert report["programme_count"] == 1
    assert root.find("channel/display-name").text == "MAGENTA SPORT 1"
    assert root.find("programme/title").text == "Programme for 550"


def test_generate_xmltv_writes_xml_and_gzip(tmp_path, monkeypatch):
    import epgforgearr.generator as generator

    monkeypatch.setattr(generator, "_provider_factory", lambda _provider: FakeProvider())
    out = tmp_path / "supplement.xml"
    result = generate_xmltv({
        "days": 1,
        "output_path": str(out),
        "gzip_output": True,
        "mapping_config_json": json.dumps([
            {"channel_id": "test.channel", "display_name": "Test Channel", "sources": [{"provider": "fake", "provider_channel_id": "abc"}]}
        ]),
    }, provider_factory=lambda _provider: FakeProvider())
    assert result["status"] == "ok"
    assert out.exists()
    assert out.with_suffix(".xml.gz").exists()
    ET.parse(out)
    gzip.decompress(out.with_suffix(".xml.gz").read_bytes())


def test_export_mapping_template_uses_only_selected_items(tmp_path):
    suggestions = tmp_path / "suggestions.json"
    mapping = tmp_path / "mapping.selected.json"
    suggestions.write_text(json.dumps({
        "schema": "epgforgearr.suggestions.v1",
        "items": [
            {
                "selected": True,
                "channel_id": "MAGENTA.SPORT1.de",
                "channel_uuid": "uuid-1",
                "channel_name": "MAGENTA SPORT 1",
                "stream_id": 101,
                "stream_name": "MAGENTA SPORT 1",
                "existing_epg": False,
                "candidates": [
                    {"provider": "magenta", "provider_channel_id": "550", "label": "Sport 1 - myTeamTV", "confidence": "medium", "reason": "number match", "priority": 10}
                ],
            },
            {
                "selected": False,
                "channel_id": "unsafe.channel",
                "channel_name": "Unsafe",
                "candidates": [
                    {"provider": "magenta", "provider_channel_id": "999", "label": "Unsafe", "confidence": "low", "reason": "contains", "priority": 50}
                ],
            },
        ],
    }), encoding="utf-8")

    result = export_mapping_template({"suggestions_path": str(suggestions), "mapping_path": str(mapping)})
    assert result["status"] == "ok"
    assert result["mapping_count"] == 1
    exported = json.loads(mapping.read_text(encoding="utf-8"))
    assert exported[0]["channel_id"] == "MAGENTA.SPORT1.de"
    assert exported[0]["sources"][0]["provider_channel_id"] == "550"


def test_generate_full_provider_epg_maps_whole_channel_list(tmp_path):
    provider = RecordingProvider([
        {"contentId": "550", "name": "Sport 1 - myTeamTV"},
        {"contentId": "35", "name": "Das Erste"},
        {"name": "broken-entry-without-id"},
    ])

    out = tmp_path / "magenta-full.xml"
    result = generate_full_provider_epg(
        {"output_path": str(out), "days": 1, "gzip_output": False},
        provider_factory=lambda _provider_id: provider,
    )
    assert result["status"] == "ok"
    assert result["provider_channel_count"] == 2
    assert sorted(provider.calls) == ["35", "550"]

    root = ET.parse(out).getroot()
    channel_ids = {c.attrib["id"] for c in root.findall("channel")}
    assert channel_ids == {"magenta.550", "magenta.35"}
    assert len(root.findall("programme")) == 2


def test_generate_full_provider_epg_maps_tvdigital_channel_list(tmp_path):
    provider = RecordingProvider([
        {"id": "37", "name": "Das Erste", "img": "das-erste.png"},
        {"id": "38", "name": "ZDF", "img": "zdf.png"},
        {"name": "broken-entry-without-id"},
    ])

    out = tmp_path / "tvdigital-full.xml"
    result = generate_full_provider_epg(
        {"output_path": str(out), "days": 1, "gzip_output": False, "full_provider": "tvdigital_de"},
        provider_factory=lambda _provider_id: provider,
    )
    assert result["status"] == "ok"
    assert result["provider"] == "tvdigital_de"
    assert result["provider_channel_count"] == 2
    assert sorted(provider.calls) == ["37", "38"]

    root = ET.parse(out).getroot()
    channel_ids = {c.attrib["id"] for c in root.findall("channel")}
    assert channel_ids == {"tvdigital_de.37", "tvdigital_de.38"}
    assert len(root.findall("programme")) == 2


def test_generate_full_provider_epg_rejects_unregistered_provider(tmp_path):
    result = None
    try:
        generate_full_provider_epg({"output_path": str(tmp_path / "out.xml"), "full_provider": "does-not-exist"})
    except ValueError as exc:
        result = str(exc)
    assert result == "unsupported full_provider: does-not-exist"
