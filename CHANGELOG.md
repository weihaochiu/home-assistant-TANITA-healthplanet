# Changelog

## 0.1.0 — Unreleased

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
- Fixed website row parsing, all-primary failure semantics, authentication propagation, and privacy-safe per-kind diagnostics for the v0.1.0 real-device candidate.

No release or tag has been created.
