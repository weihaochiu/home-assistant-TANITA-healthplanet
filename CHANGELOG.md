# Changelog

## 0.2.3 — 2026-08-28

### Reliability fixes

- Fixed invalid external statistic IDs for Home Assistant installations whose config-entry identifiers contain uppercase characters.
- Fixed false installation-drift detection caused by comparing `0.2.x` with HACS `v0.2.x` strings without semantic normalization.
- Hardened cleanup of the legacy Integration Management device.
- Improved privacy-safe OAuth token-exchange diagnostics for real-device troubleshooting.
- Added detection of stale HACS update metadata without bypassing HACS for installation.
- Removed release-build version hard-coding.

## 0.2.2 — 2026-08-28

### Reliability fixes

- Verified historical imports through Home Assistant Recorder before reporting records as imported, with privacy-safe failure stages and error types.
- Documented the supported external-statistics target and Home Assistant History-panel limitation without forging historical states.
- Added a validated deterministic HACS release ZIP with manifest, layout, checksum, and secret-audit gates.
- Added disk-manifest verification and explicit HACS metadata/installed-file drift detection to Safe Update.
- Hardened manual HealthPlanet authorization-code exchange with exact success-URL parsing and allowlisted OAuth error diagnostics.
- Added the integration software version to stable family-device metadata.
- Removed the separate Integration Management device while retaining one installation-wide Safe Update control.
- Clarified HACS installation, Add Integration, recovery, and generated release notes.

## 0.2.1 — 2026-08-27

- Added automatic GitHub Release creation for validated semantic-version tags.
- Added release/version consistency gates using GitHub Actions and the repository-scoped `GITHUB_TOKEN`.
- Updated the original project branding with the owner-selected smart scale, cloud, and smart-home synchronization icon.
- Preserved the unofficial branding policy without bundling TANITA or HealthPlanet official artwork.
- Added a native Safe Update feature that creates and verifies a Home Assistant backup before installing a HACS update, then optionally restarts Home Assistant after successful installation.
- Included Safe Update with the HACS integration so no separate Blueprint, add-on, or second integration is required.

## 0.2.0 — 2026-08-27

- Added Hybrid-only setup for new accounts.
- Added family-member labels and multi-account UX.
- Replaced incompatible callback OAuth with a HealthPlanet-compatible manual authorization-code flow.
- Added shared per-Home-Assistant Application Credentials support.
- Added historical synchronization using provider measurement timestamps.
- Added official 90-day and Website 31-day history support.
- Added `measurement_time` attributes and an in-device Sync history button.
- Added original local integration branding without TANITA or HealthPlanet official artwork.
- Preserved v0.1.x Website-only and Official-only entries for migration and recovery.
- Renamed the user-facing integration to "HealthPlanet for Home Assistant" to make its unofficial and independent status clearer.
- Added explicit unofficial-project and trademark notices.

The Website source remains experimental because its endpoint is undocumented and may change.

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
