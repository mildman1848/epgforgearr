# EPGForgearr

EPGForgearr is a standalone Dispatcharr plugin that generates supplemental XMLTV EPG files from direct upstream provider APIs and installs them as local Dispatcharr EPG sources.

The plugin is intentionally split from stream import/resolver work:

- **Kodiboxarr** imports and updates streams only.
- **Vavooarr** is the future resolver/source adapter boundary for Vavoo-style streams.
- **EPGForgearr** generates and manages EPG sources only.

No Dispatcharr Channels are created automatically. Channel creation and stream linking stay user-owned inside Dispatcharr.

## Current provider status

| Provider ID | Source | Status | Output |
|---|---|---|---|
| `magenta` | Magenta TV EPG direct API | implemented | `/data/epgforgearr/magenta-full.xml(.gz)` |
| `tvdigital_de` | TV Digital DE direct API | implemented | `/data/epgforgearr/tvdigital-de-full.xml(.gz)` |
| `ewtn_de` | EWTN Deutschland public daily schedule | implemented | `/data/epgforgearr/ewtn-de-full.xml(.gz)` |
| `bibeltv_impuls` | Bibel TV Impuls official programme page (structured page data) | implemented | `/data/epgforgearr/bibeltv-impuls-full.xml(.gz)` |
| `freeepg_de` | FreeEPG Germany XMLTV feed | implemented | `/data/epgforgearr/freeepg-de-full.xml(.gz)` |
| `freeepg_ch` | FreeEPG Switzerland XMLTV feed | implemented | `/data/epgforgearr/freeepg-ch-full.xml(.gz)` |
| `simpli_tv` | SimpliTV / PULS24 AT | planned | not generated yet |

Michaz' public EPG scripts are used as endpoint/field references only. EPGForgearr does **not** consume Michaz-generated aggregate XMLTV as a provider.

## Project links and attribution

- **Dispatcharr:** [Dispatcharr/Dispatcharr](https://github.com/Dispatcharr/Dispatcharr) — host application and plugin integration.
- **Magenta TV:** provider API adapter implemented by EPGForgearr; independent of the provider.
- **TV Digital DE:** [TV Digital](https://www.tvdigital.de/) — guide data provider accessed through its public service API.
- **EWTN Deutschland:** [EWTN Programm](https://ewtn.de/programm/) — public day pages, read directly; no formal programme API is documented.
- **FreeEPG:** [free-epg.de](https://free-epg.de/countries/de) — free XMLTV feed for Germany; its current channel list does not include EWTN.
- **EPG reference scripts:** [michaz1988/michaz1988.github.io](https://github.com/michaz1988/michaz1988.github.io/tree/main/.epg) — endpoint/field reference only; generated aggregate XMLTV is not consumed as a provider.
- **Related stream plugin:** [Kodiboxarr](https://github.com/mildman1848/kodiboxarr) imports streams separately; EPGForgearr also works as a standalone supplemental EPG plugin.

This project is maintained independently by Mildman1848 and is not affiliated with or endorsed by Dispatcharr, Magenta TV, TV Digital, or the reference-script author.

## Main workflow

Recommended production-safe flow:

1. `scan_missing_epg`
   - scans Dispatcharr streams/channels for EPG gaps
   - fetches the channel lists of all usable providers and ranks candidates by
     confidence, with provider attribution and IDs
   - reports `provider_coverage` (mapping coverage per provider) separately from
     `stream_availability`; adds `programme_availability` per provider (last-known
     `programme_count`, `coverage_window`, `last_success_at`, `last_status`) read
     from the persisted scheduler state only. It is cached and may be stale, is
     `null`/`known: false` when no successful refresh is persisted, and the scan
     never fetches schedules
   - writes review file: `/data/epgforgearr/review/suggestions.json`
2. User review
   - edit `selected` per item
   - optionally replace `chosen_candidate` with another candidate
3. `export_mapping_template`
   - writes `/data/epgforgearr/review/mapping.selected.json`
   - only `selected=true` items are exported
4. `generate_from_mapping`
   - writes `/data/epgforgearr/epgforgearr.xml(.gz)`
5. `install_epg_source`
   - creates or updates the Dispatcharr EPG source for the generated local XMLTV file
6. Dispatcharr EPG refresh parses the source.

For full-provider generation, use:

```text
generate_all_provider_sources
```

That action generates one XMLTV file and one Dispatcharr `EPGSource` per usable provider, for example:

- `EPGForgearr: Magenta`
- `EPGForgearr: TV Digital DE`

## Actions

- `list_sources` — list provider adapters
- `scheduler_status` — show persisted scheduler state
- `scan_missing_epg` — scan streams/channels and write suggestions
- `export_mapping_template` — convert reviewed suggestions to selected mapping JSON
- `validate_mapping` — validate inline mapping JSON
- `generate_epg` — legacy inline mapping generation
- `generate_from_mapping` — generate XMLTV from selected mapping file
- `install_epg_source` — create/update Dispatcharr EPGSource
- `generate_and_install` — mapping-based generation + install
- `generate_full_provider_epg` — generate a single provider full EPG
- `generate_full_and_install` — generate + install one provider source
- `generate_all_provider_sources` — generate + install every usable provider source

## Safety notes

- Suggestions are not auto-selected by default.
- Low-confidence matches are review-only.
- Exact-looking matches can still be wrong when `tvg_id` variants point to a base channel, e.g. plus/up/timeshift variants.
- The plugin does not create Dispatcharr Channels and does not change user channel mapping.
- Dispatcharr only imports programme rows for EPG IDs that are mapped to Channels. A generated source can therefore show EPG entries but zero programme rows until Channels use matching `tvg_id`s.
- XMLTV and gzip outputs are written atomically via same-directory temp files and `os.replace()` to avoid stale ownership problems from manual root-run tests.

## Development

Create a local virtual environment and install test dependencies:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install pytest requests
```

Run tests:

```bash
python3 -m pytest -q
```

Build a Dispatcharr plugin ZIP:

```bash
python3 scripts/build_plugin_zip.py
```

## Current verified smoke

Latest controlled Dispatcharr test generated and installed:

| Source | Channels | Programmes |
|---|---:|---:|
| `EPGForgearr: Magenta` | 331 | 29603 |
| `EPGForgearr: TV Digital DE` | 103 | 13595 |

Both generated `.xml.gz` files were parseable and owned by the Dispatcharr runtime user.

## License

AGPL-3.0-only. See [LICENSE](LICENSE).
