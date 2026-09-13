from __future__ import annotations

import plugin


def _manifest_defaults() -> dict:
    return plugin._merge_defaults({"full_provider": "tvdigital_de"})


def test_single_provider_settings_replaces_legacy_magenta_defaults_for_tvdigital():
    settings = plugin._single_provider_settings(_manifest_defaults())

    assert settings["full_provider"] == "tvdigital_de"
    assert settings["output_path"] == "/data/epgforgearr/tvdigital-de-full.xml"
    assert settings["epg_source_name"] == "EPGForgearr: TV Digital DE"
    assert settings["epg_source_priority"] == 70


def test_single_provider_settings_preserves_explicit_user_overrides():
    raw = _manifest_defaults()
    raw.update({
        "output_path": "/data/custom.xml",
        "epg_source_name": "Custom TVD",
        "epg_source_priority": 123,
    })

    settings = plugin._single_provider_settings(raw)

    assert settings["output_path"] == "/data/custom.xml"
    assert settings["epg_source_name"] == "Custom TVD"
    assert settings["epg_source_priority"] == 123
