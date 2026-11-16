# Changelog

## 0.4.0 — 2026-11-16

- Added the `bibeltv_impuls` provider using schedule data embedded in Bibel TV's public Impuls programme page; it has its own output file and Dispatcharr EPG source.
- Added `Bibel TV Impuls` to the selectable full-provider list.

## Unreleased (0.5.0)

- Added independent enable/disable settings for every usable EPG provider; scans and daily refresh now honor the selected combination.
- Reduced visible plugin actions to Scan, Install sources, Generate EPG for sources, and Install sources and generate EPG. Separate install and generation actions no longer implicitly perform the other step.

- Added the `bibeltv_impuls` provider using schedule data embedded in Bibel TV's public Impuls programme page; it has its own output file and Dispatcharr EPG source.
- Added `Bibel TV Impuls` to the selectable full-provider list.

- Added `freeepg_ch` from FreeEPG's Swiss XMLTV feed with an independent selectable profile, output and Dispatcharr EPGSource.
- Fixed FreeEPG XML parsing to retain child display names and programme fields until each complete XMLTV element is parsed.
- FreeEPG lists Bibel TV Impuls and Bibel TV Musik in its Germany directory, but neither ID is present in the current downloaded German XMLTV feed; only Bibel TV main has confirmed programme rows. Do not map those variants to Bibel TV main.
- Provider instances are now cached once per XMLTV build, avoiding repeated feed downloads for multi-channel providers.

- `scan_missing_epg` now searches all usable provider channel lists, ranks and
  attributes candidates by provider, and reports mapping coverage separately
  from existing stream EPG assignments. Ambiguous matches remain unselected;
  the scan also reports cached `programme_availability` per provider (last-known
  programme count, coverage window and last success from persisted scheduler
  state; null when unknown, possibly stale, never fetched live).
- Added fixture-backed tests for cross-provider candidates, ranking, coverage,
  provider failures, no-match behavior, and backwards-compatible mapping export.

## 0.3.8 — 2026-11-15

- Added `ewtn_de` and `freeepg_de` provider adapters with separate generated XMLTV outputs and Dispatcharr EPG sources.
- Cached provider instances across channel mappings to avoid repeating provider initialization and feed downloads.

## 0.3.7 — 2026-11-07

- Failed provider refreshes (any channel error) no longer replace the last good
  XMLTV/gzip output; the run is reported as an error with the output preserved.
- Generation that yields zero usable mappings is blocked when it would overwrite
  an existing non-empty XMLTV or gzip file. A genuinely empty schedule is still
  written as valid output.
- XMLTV and gzip are now staged first and published together; if publishing the
  gzip fails, the XML is rolled back (or removed if there was no previous file).
  If rollback itself fails, a backup is kept and its path is reported.
- Scheduler state records per-provider health: last attempt and last success
  time, coverage window (from programme timestamps), channel/programme counts,
  and a sanitized last error. Previous success data is retained after a failure.
  Full refresh state now uses UTC ISO timestamps, and `last_full_refresh`
  advances only on success.
- Error text stored or logged is sanitized (URLs, tokens, passwords, API keys,
  signatures, cookies and long opaque strings are redacted); several error logs
  now record only the exception type instead of tracebacks/messages.
- Installing the Dispatcharr EPG source no longer claims success up front: new
  sources start as `idle`, existing sources get a forced refresh queued (unless
  one is running), and the action briefly waits (default 3 s, max 5 s,
  `epg_import_wait_seconds`) and reports `ok`, `warning` (channels but no
  programmes), `pending`, or `error` from Dispatcharr's actual import state.
- Tests added/extended for the above (66 tests pass locally).

Not verified: persisted health through a full scheduled refresh in a real
Dispatcharr runtime (ROADMAP item 2 remains open). `ruff check .` over the whole
repo reports pre-existing findings; the CI rule set was not re-run here.
