from __future__ import annotations

import plugin


def test_plugin_routes_three_provider_actions_to_separate_modes(monkeypatch):
    calls = []

    def fake_sources(settings, logger=None, *, generate=True, install=True):
        calls.append((generate, install, settings.get("source_magenta")))
        return {"status": "ok"}

    monkeypatch.setattr(plugin, "generate_all_provider_sources", fake_sources)
    instance = plugin.Plugin.__new__(plugin.Plugin)

    for action in ("install_provider_sources", "generate_provider_epgs", "install_and_generate_provider_epgs"):
        assert instance.run(action, {"settings": {"source_magenta": True}}, {})["status"] == "ok"

    assert calls == [(False, True, True), (True, False, True), (True, True, True)]


def test_plugin_rejects_removed_actions():
    instance = plugin.Plugin.__new__(plugin.Plugin)
    assert instance.run("generate_all_provider_sources", {}, {})["status"] == "error"
