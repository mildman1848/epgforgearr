# Kodiboxarr / Vavooarr / EPGForgearr Architecture

## Decision

Split the current work into clear plugin responsibilities:

| Plugin | Responsibility | Writes Channels? | Notes |
|---|---|---:|---|
| `Kodiboxarr` | Watch Kodibox builds, extract playlist/cache/metadata, maintain Dispatcharr M3U account streams | No | Sync updates streams only. Explicit channel helper actions remain opt-in tooling only. |
| `Vavooarr` (planned) | Runtime Vavoo resolver / source adapter: MediaHubMX signature, mirror candidate rotation, health probes | No | Today this code lives in `Kodiboxarr/resolver.py`; extract when another importer needs Vavoo too. |
| `EPGForgearr` | Supplemental XMLTV generator with selectable sources per station | No | Standalone plugin. First adapter: Magenta TV based on michaz1988 `.epg/make_guide.py`. |

This avoids one overgrown plugin that imports streams, resolves playback and invents EPG at the same time. That would work, but so would storing secrets in a spreadsheet. Humans do these things. We do not encourage them.

## Why split

- **Security:** EPG providers and stream resolvers have different network/API risk profiles.
- **Maintainability:** Kodibox build parsing should not depend on Magenta TV or TV Digital response shapes.
- **User control:** Dispatcharr users decide which streams become channels and which EPG source a channel uses.
- **Reuse:** A standalone EPG plugin can later help non-Kodibox streams too.

## EPGForgearr settings model

The implementation uses reviewable JSON files because Dispatcharr plugin settings do not currently provide a dynamic table UI.

Workflow files:

| File | Purpose |
|---|---|
| `/data/epgforgearr/review/suggestions.json` | Scanner output with provider candidates and `selected` flags |
| `/data/epgforgearr/review/mapping.selected.json` | User-reviewed mapping used for generation |
| `/data/epgforgearr/epgforgearr.xml(.gz)` | Generated XMLTV supplemental EPG (mapping-based generation) |
| `/data/epgforgearr/magenta-full.xml(.gz)` | Full Magenta TV channel list XMLTV, installed as its own Dispatcharr EPGSource |
| `/data/epgforgearr/tvdigital-de-full.xml(.gz)` | Full TV Digital DE channel list XMLTV, installed as its own Dispatcharr EPGSource |

Each usable provider gets its own output file and its own managed Dispatcharr
EPGSource (never a shared/merged source) so Channels can be mapped per
provider without one provider's refresh clobbering another's. Defaults for
output path, EPGSource name and priority live in `provider_profile()` in
`epgforgearr/workflow.py`. `generate_all_provider_sources` (daily
self-scheduler and the "Generate all provider EPG sources" action) runs this
for every usable provider; planned-only providers (currently `simpli_tv`) are
skipped until they get a real adapter.

Example selected mapping:

```json
[
  {
    "channel_id": "DAZN.BAR1.de",
    "display_name": "DAZN BAR 1",
    "sources": [
      {"provider": "magenta", "provider_channel_id": "550", "label": "Sport 1 - myTeamTV", "priority": 1},
      {"provider": "tvdigital_de", "provider_channel_id": "12188", "label": "TV Digital DAZN 1", "priority": 20}
    ]
  }
]
```

Future UI target: source picker per station:

1. Plugin scans missing EPG IDs from Dispatcharr.
2. Provider adapters return candidate channels.
3. User selects the source per station from a dropdown/list.
4. Plugin writes a mapping JSON file and generates XMLTV.

## Source adapter roadmap

Michaz is a useful reference because it already combines several source flows,
but EPGForgearr should use those upstream sources directly instead of consuming
Michaz' generated XMLTV as a provider. This keeps freshness, attribution, error
handling and source selection under our control.

1. `magenta` — implemented as PoC adapter (`AllChannel`, `PlayBillList`).
2. `tvdigital_de` — adapt TV Digital channel list/programme fetch directly from the source flow Michaz uses.
3. `simpli_tv` — adapt Austrian/PULS source directly from the source flow Michaz uses.
4. `waipu`, `zatoo`, `samsung_tv_plus` or other direct sources — evaluate after coverage gaps are known.
5. Provider health + freshness report.
6. Candidate search across all providers for missing Dispatcharr EPG IDs.

## Channel policy

No plugin should automatically create Dispatcharr channels. Streams are imported; channels and stream chaining are user-owned. This is not just preference — it prevents silent duplicates and wrong EPG mappings.
