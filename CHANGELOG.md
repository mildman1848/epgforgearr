# Changelog

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
