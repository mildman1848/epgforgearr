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
**Blocked** — a verified source or prerequisite is needed;
**Done** — implemented and verified.

### 1. Direct provider adapter coverage — Blocked (source not verified)

Tracking: [#7](https://github.com/mildman1848/epgforgearr/issues/7)

- Initial public-source review found simpliTV channel-lineup documents but did not
  verify a direct machine-readable programme schedule feed or schema.
- Do not consume a third-party aggregate or invent an undocumented endpoint.
- Resume adapter work when an official direct feed/specification or permitted
  fixture is available; see the progress note on issue #7.

### 2. Provider health and freshness — In progress

Tracking: [#8](https://github.com/mildman1848/epgforgearr/issues/8)

- [x] Record per-provider last attempt/success, coverage window from programme
  timestamps, channel/programme counts, and sanitized errors in scheduler state.
- [x] Distinguish a genuinely empty schedule from fetch failures; preserve the
  last good XMLTV and gzip outputs when a provider refresh fails.
- [x] Test coverage calculations, redaction, empty schedules, last-good output
  preservation (including gzip-publish and rollback failures), and provider-health
  retention locally (48 tests pass; Ruff CI rules pass).
- [ ] Verify persisted health through a full scheduled refresh with Dispatcharr's
  real provider/runtime environment before closing the milestone.

Local implementation is not yet released or deployed.

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
