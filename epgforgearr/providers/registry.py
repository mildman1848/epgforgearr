from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List


class ProviderRegistry:
    """Registry of EPG provider adapters, keyed by provider id.

    New sources (beyond Magenta) register themselves here once; generator.py
    and workflow.py then resolve providers generically instead of branching
    on provider id strings. A provider can also be listed as "planned"
    (metadata only, no factory yet) so it shows up in `list_sources` without
    being selectable for generation.
    """

    def __init__(self) -> None:
        self._factories: Dict[str, Callable[[], Any]] = {}
        self._metadata: Dict[str, Dict[str, Any]] = {}

    def register(
        self,
        provider_id: str,
        factory: Callable[[], Any],
        *,
        label: str | None = None,
        status: str = "poc",
        supports: Iterable[str] | None = None,
        notes: str = "",
    ) -> None:
        """Register a usable provider adapter (has a working factory)."""
        self._factories[provider_id] = factory
        self._metadata[provider_id] = {
            "id": provider_id,
            "label": label or provider_id,
            "status": status,
            "supports": list(supports or []),
            "notes": notes,
        }

    def register_planned(
        self,
        provider_id: str,
        *,
        label: str | None = None,
        supports: Iterable[str] | None = None,
        notes: str = "",
    ) -> None:
        """Register a future provider for discoverability only; no factory yet."""
        self._metadata[provider_id] = {
            "id": provider_id,
            "label": label or provider_id,
            "status": "planned",
            "supports": list(supports or []),
            "notes": notes,
        }

    def is_registered(self, provider_id: str) -> bool:
        """True only if the provider has a usable factory (not just planned)."""
        return provider_id in self._factories

    def create(self, provider_id: str) -> Any:
        try:
            factory = self._factories[provider_id]
        except KeyError:
            raise ValueError(f"unsupported provider: {provider_id}") from None
        return factory()

    def ids(self) -> List[str]:
        return list(self._factories.keys())

    def describe_all(self) -> List[Dict[str, Any]]:
        """Metadata for every registered provider, usable and planned alike."""
        return [dict(meta) for meta in self._metadata.values()]
