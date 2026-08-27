# Changelog

## 0.1.1 — 2026-08-27

- Fixed experimental Website row parsing observed during the first HACS-installed real-device test.
- Added deterministic timestamp/value role assignment instead of requiring exactly one timestamp-looking field.
- Expanded safe timestamp parsing for supported Website representations.
- Split missing timestamp and truly ambiguous-row diagnostics.
- Added real-device-derived synthetic regression coverage without storing real health values or timestamps.
- Preserved all-primary failure semantics and provider isolation.

The Website source remains experimental because its endpoint is undocumented and may change.

## 0.1.0 — 2026-08-27

- Added a HACS-compatible Home Assistant integration with multi-entry config flows.
- Added My Home Assistant buttons for opening the repository in HACS and starting the TANITA HealthPlanet config flow.
- Added Official-first Hybrid, Official-only, and experimental Website-only modes.
- Added Home Assistant Application Credentials OAuth with the documented `innerscan,sphygmomanometer` scope.
- Added official systolic/diastolic blood pressure and pulse sensors with exact-timestamp complete-pair selection.
- Split Official and Website coordinators, polling intervals, authentication handling, availability, and diagnostics.
- Added safe migration of v1 entries, source-specific reauthentication, and Website-only to Hybrid reconfiguration.
- Kept the experimental website provider behind explicit opt-in and limited it to eight non-overlapping metrics in Hybrid mode.
- Added reauthentication, conservative polling, partial-failure handling, diagnostics redaction, English and Traditional Chinese translations, and unload/session cleanup.
- Added synthetic-only tests, pinned CI, HACS validation, Hassfest, and deep privacy auditing.
- Added initial website row parsing, all-primary failure semantics, authentication propagation, and privacy-safe per-kind diagnostics for the real-device candidate.
