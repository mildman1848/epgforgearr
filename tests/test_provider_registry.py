from __future__ import annotations

import pytest

from epgforgearr.providers import default_registry
from epgforgearr.providers.registry import ProviderRegistry


def test_default_registry_lists_magenta_and_tvdigital_as_usable_and_simpli_tv_as_planned():
    described = {entry["id"]: entry for entry in default_registry.describe_all()}
    assert described["magenta"]["status"] == "poc"
    assert default_registry.is_registered("magenta")
    assert described["tvdigital_de"]["status"] == "poc"
    assert default_registry.is_registered("tvdigital_de")
    assert described["simpli_tv"]["status"] == "planned"
    assert not default_registry.is_registered("simpli_tv")


def test_default_registry_creates_magenta_provider_instance():
    provider = default_registry.create("magenta")
    assert hasattr(provider, "list_channels")
    assert hasattr(provider, "fetch_programmes")


def test_default_registry_creates_tvdigital_provider_instance():
    provider = default_registry.create("tvdigital_de")
    assert hasattr(provider, "list_channels")
    assert hasattr(provider, "fetch_programmes")


def test_registry_create_unknown_provider_raises_value_error():
    registry = ProviderRegistry()
    with pytest.raises(ValueError, match="unsupported provider: nope"):
        registry.create("nope")


def test_registry_register_and_create_roundtrip():
    registry = ProviderRegistry()
    sentinel = object()
    registry.register("dummy", lambda: sentinel, label="Dummy", status="poc", supports=["channel_list"])
    assert registry.is_registered("dummy")
    assert registry.create("dummy") is sentinel
    assert registry.ids() == ["dummy"]
    assert registry.describe_all() == [
        {"id": "dummy", "label": "Dummy", "status": "poc", "supports": ["channel_list"], "notes": ""}
    ]


def test_registry_planned_provider_not_creatable():
    registry = ProviderRegistry()
    registry.register_planned("future", label="Future Source")
    assert not registry.is_registered("future")
    with pytest.raises(ValueError):
        registry.create("future")
    assert registry.describe_all()[0]["status"] == "planned"
