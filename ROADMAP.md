# EPGForgearr Roadmap

EPGForgearr generates supplemental XMLTV data from direct provider adapters and
manages provider-specific Dispatcharr EPG sources. It does not create Channels,
link streams, or replace user-controlled EPG mappings.

## Principles

- Keep provider adapters independent and attributable; do not consume an
  upstream-generated aggregate XMLTV as if it were a direct provider.
- Preserve one generated XMLTV output and managed Dispatcharr EPG source per
  usable provider so refreshes cannot overwrite another provider's data.
- Keep suggestions reviewable; never auto-select uncertain matches or change
  Channel mappings silently.
- Treat provider failures and stale data as visible health state, not as a
  successful empty guide.
- Cover adapters with fixtures and deterministic tests; avoid live-provider
  requirements in CI.

## Milestones

Status: **Next** — planned; **In progress** — implementation underway;
**Done** — implemented and verified.

### 1. Direct provider adapter coverage — Next

Tracking: [#7](https://github.com/mildman1848/epgforgearr/issues/7)

- Implement the planned `simpli_tv` adapter for Austrian/PULS24 schedules using
  a documented direct-source flow.
- Keep the adapter behind the existing provider registry/profile contract.
- Produce provider-specific XMLTV and Dispatcharr EPGSource outputs.
- Add fixture tests for channel normalization, programme parsing, timezone,
  empty/error responses, and XMLTV validity.

### 2. Provider health and freshness — Next

Tracking: [#8](https://github.com/mildman1848/epgforgearr/issues/8)

- Report per-provider last successful fetch, schedule coverage window, channel
  and programme counts, and sanitized last error.
- Distinguish a genuinely empty schedule from network, parse, and authentication
  failures; do not replace a valid output with empty data on failed refresh.
- Preserve atomic writes and independent per-provider outputs.
- Add tests for stale data and failed refresh preserving the last good output.

### 3. Candidate search and coverage review — Next

Tracking: [#9](https://github.com/mildman1848/epgforgearr/issues/9)

- Search candidates across all usable provider channel lists for missing EPG IDs.
- Present provider attribution, match confidence, and identifiers in the existing
  review workflow; uncertain matches remain unselected.
- Report mapping coverage and programme availability per provider without
  conflating stream availability with EPG availability.
- Keep manual mapping JSON workflow supported and backward compatible.

### 4. Provider expansion — Later

- Evaluate additional direct providers (for example Waipu, Zattoo, or Samsung TV
  Plus) only after measured coverage gaps justify the maintenance cost.
- For every candidate, document source/access assumptions, data freshness,
  rate limits, and failure behavior before implementation.
- Do not add a provider merely because its name appears in another plugin's
  build; stream and EPG source responsibilities remain separate.

### 5. Release and compatibility verification — Next

- Keep plugin action/settings descriptions and provider status documentation in
  sync with the registry and real adapter availability.
- Run unit tests, lint/validation, plugin ZIP build, and GitHub Actions.
- Verify generated XMLTV and managed EPGSource behavior in a controlled
  Dispatcharr instance before production rollout; no Channel mappings are changed.
