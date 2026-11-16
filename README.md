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

1. Choose any combination of provider toggles in the plugin settings.
2. Run `Scan` to create reviewable channel/provider suggestions.
3. Choose `Generate EPG for sources` to write files only, `Install sources` to register existing files in Dispatcharr, or `Install sources and generate EPG` to do both.
4. Dispatcharr imports each installed XMLTV source; Channels still need matching EPG IDs to receive programme rows.

The daily refresh, when enabled, generates and installs only the selected providers.

## Source actions

- Select any combination of providers in the plugin settings. The selection applies to scans, manual source actions and the daily auto-refresh.
- `Install sources` creates/updates selected Dispatcharr EPG sources from XMLTV files that already exist.
- `Generate EPG for sources` writes selected XMLTV files without installing or refreshing Dispatcharr sources.
- `Install sources and generate EPG` performs both steps for each selected provider.

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
