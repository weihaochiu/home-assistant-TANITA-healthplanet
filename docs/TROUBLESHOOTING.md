# Troubleshooting

## Reauthentication requested

Open the integration's reauthentication notification. Official reauthentication opens HealthPlanet, then asks you to copy the one-time code back to Home Assistant within 10 minutes. It does not return through My Home Assistant. Website reauthentication asks only for new Website credentials. The failing source is repaired without clearing the other source's credentials or data.

## Missing Application Credentials

Follow the [API application setup guide](HEALTHPLANET_API_SETUP.md). One Client ID / Client Secret is shared by all family members on one Home Assistant; do not enter the HealthPlanet Website login in Application Credentials.

## Historical sync failed

Current sensors remain available because history is a separate failure domain. Retry with the device's **Sync history** button. Official history is capped at 90 days, Website history at 31 days, and Recorder statistics are hourly even though `measurement_time` preserves the exact provider time.

## Brand icon missing

Restart after installing the complete release and confirm `custom_components/tanita_healthplanet/brand/` exists. The Home Assistant integration icon and HACS repository-list icon use different frontend paths; a HACS placeholder can remain an external local-brand limitation even when Devices & services displays the icon correctly.

## One source or sensor is unavailable

Official and Website coordinators fail independently. Inspect the redacted diagnostics for `official.innerscan`, `official.sphygmomanometer`, or `website.per_kind`. Missing/null data stays unavailable and never becomes zero. Kind 23 may legitimately be null without affecting other kinds.

Blood-pressure sensors need an exact-timestamp systolic/diastolic pair. Pulse also needs that same timestamp. A newer incomplete group is intentionally ignored; if no complete pair exists, all blood-pressure values remain unavailable.

## Website source stopped working

The website endpoint is unofficial and may change or disappear without warning. A challenge/MFA page, changed login form, HTML graph response, or blocked automation triggers a controlled error or reauthentication. Complete any legitimate manual account action on the official site yourself, then retry later; do not bypass challenges. Do not increase polling frequency: the minimum is 30 minutes and the default is 60.

Version 0.1.1 fixes a Website row-parser compatibility issue discovered during the first HACS-installed real-device test. Redacted diagnostics distinguish these structural failures without exposing row contents:

- `website_record_timestamp_missing`: no valid timestamp candidate was found.
- `website_record_timestamp_ambiguous`: more than one valid timestamp/value role assignment remains.
- `website_record_fields_invalid`: a timestamp role exists, but the other field is not a valid numeric measurement.

The optional `row_length`, candidate counts, assignment count, and `field_type_shape` diagnostics contain only structural types and counts. Do not share raw rows to investigate these errors.

## Upgrade through HACS

Use Home Assistant's normal update entity or HACS update action for the published release, then restart Home Assistant if requested. Do not use Redownload or manually overwrite `custom_components` when testing update detection. Existing Website entries and stored credentials remain in place. Existing v1 Website entries migrate to Website-only without password re-entry; use Reconfigure to upgrade to Hybrid. Existing Official entries need reauthentication to grant the new sphygmomanometer scope.

## Reporting a problem

Share only redacted diagnostics. Never post credentials, client secrets, OAuth codes/tokens, Cookie/Set-Cookie, CSRF tokens, raw HTML/JSON, request/response bodies, health values, measurement timestamps, or screenshots that reveal them. GitHub issues are public unless the repository explicitly says otherwise.

## Removing the integration

Remove all **HealthPlanet for Home Assistant** config entries under Devices & services, uninstall the repository through HACS, and restart Home Assistant. If exposure is suspected, also revoke the OAuth grant and change the Website password.
