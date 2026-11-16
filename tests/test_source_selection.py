from __future__ import annotations

from epgforgearr.workflow import selected_provider_ids


def test_selected_provider_ids_supports_arbitrary_boolean_combinations():
    settings = {f"source_{provider_id}": False for provider_id in selected_provider_ids({})}
    settings["source_magenta"] = True
    settings["source_bibeltv_impuls"] = True
    assert selected_provider_ids(settings) == ["magenta", "bibeltv_impuls"]


def test_selected_provider_ids_defaults_to_all_for_legacy_settings():
    assert len(selected_provider_ids({})) >= 6


def test_selected_provider_ids_rejects_empty_selection():
    assert selected_provider_ids({f"source_{provider_id}": False for provider_id in selected_provider_ids({})}) == []
