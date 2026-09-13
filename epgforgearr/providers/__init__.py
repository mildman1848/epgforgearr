from __future__ import annotations

from .magenta import MagentaProvider
from .registry import ProviderRegistry
from .tvdigital import TvDigitalProvider

# Single shared registry for the plugin. Adding a new source beyond Magenta
# means registering it here (or via default_registry.register(...) from a
# new provider module) - generator.py and workflow.py stay unchanged.
default_registry = ProviderRegistry()

default_registry.register(
    "magenta",
    MagentaProvider,
    label="Magenta TV EPG",
    status="poc",
    supports=["channel_list", "programme_fetch"],
    notes="Adapted from michaz1988 .epg/make_guide.py; no user credentials required, but API is unofficial.",
)
default_registry.register(
    "tvdigital_de",
    TvDigitalProvider,
    label="TV Digital DE",
    status="poc",
    supports=["channel_list", "programme_fetch"],
    notes="Direct adapter for the mobile.tvdigital.de upstream source Michaz uses; does not consume Michaz's generated XMLTV.",
)
default_registry.register_planned(
    "simpli_tv",
    label="SimpliTV / PULS24 AT",
    supports=["channel_list", "programme_fetch"],
    notes="Planned direct adapter for Austrian guide data, using source endpoints directly.",
)

__all__ = ["ProviderRegistry", "default_registry", "MagentaProvider", "TvDigitalProvider"]
