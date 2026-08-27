# HealthPlanet for Home Assistant

HealthPlanet for Home Assistant is an **unofficial** Home Assistant integration for accessing a user's own TANITA HealthPlanet measurements.

This independently developed open-source project is not affiliated with, not endorsed by, not sponsored by, and not officially supported by TANITA Corporation, TANITA Health Link, or the Home Assistant project.

## Install with HACS

[![Open this repository in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=weihaochiu&repository=home-assistant-TANITA-healthplanet&category=integration)

1. Install and configure [HACS](https://www.hacs.xyz/docs/use/download/download/).
2. Open this repository in HACS and download **HealthPlanet for Home Assistant**.
3. Restart Home Assistant.
4. Complete **Before setup**, then add the integration.

[![Add HealthPlanet for Home Assistant](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=tanita_healthplanet)

## Safe updates

When installed through HACS, HealthPlanet for Home Assistant includes a native, optional **Safe update HealthPlanet** button. No Blueprint, add-on, second integration, token, or additional HACS installation is required. The button is created once for the whole repository, not once per family member, and it only runs after an explicit press; there are no unattended updates or surprise restarts.

Before using it, configure **Settings → System → Backups**. Safe Update uses those existing automatic-backup contents, locations, encryption/password, and retention settings. When pressed, it:

1. resolves the HealthPlanet HACS update entity through Home Assistant's public registries and confirms an update is available;
2. calls `backup.create_automatic` and proves a new backup entered `in_progress` before accepting a later `completed` event;
3. calls the standard `update.install` action without a native `backup` flag;
4. verifies that the entity is no longer updating and that `installed_version` equals the captured target version;
5. optionally calls `homeassistant.restart` (enabled by default).

If automatic discovery is unavailable, open the integration's **Configure** options once and select its HACS update entity. This fallback stores the entity's HACS registry identity, so renaming the entity does not hard-code its old entity ID. The restart preference is also available in Configure and applies installation-wide.

Backup failure or timeout always blocks installation. Update failure or timeout always blocks restart. Safe Update restarts Home Assistant Core only; it never reboots the Home Assistant OS host. HACS remains responsible for repository download/install and its own rollback behavior. HACS repository update entities may not expose Home Assistant's native “Back up before updating” checkbox, so this integration creates and verifies the Home Assistant backup before invoking HACS.

Bootstrap note: v0.2.0 does not contain this code. The one-time v0.2.0 → v0.2.1 upgrade still uses the normal HACS update flow followed by a manual Home Assistant restart. Native Safe Update can then handle v0.2.1 → v0.2.2 and later updates.

## What you get

New accounts use one Hybrid entry with 13 sensors:

| Source | Metrics |
| --- | --- |
| Official HealthPlanet API | Weight, body-fat percentage, systolic pressure, diastolic pressure, pulse |
| Experimental Website source | Body-fat mass, visceral-fat level, basal metabolism, muscle mass, estimated bone mass, metabolic age, body-water percentage, muscle-quality score |

Hybrid never republishes Website kinds 1 or 2. A null muscle-quality score remains unavailable, not zero. The Website endpoint is undocumented and experimental; it may change without notice.

## Before setup

HealthPlanet requires each Home Assistant installation to register its own API application. **You need only one Client ID / Client Secret per Home Assistant.** All family members on that Home Assistant share the application, but each member authorizes their own account and receives a separate access token.

1. Install with HACS.
2. [Register one HealthPlanet API application](docs/HEALTHPLANET_API_SETUP.md).
3. Add it under **Settings → Devices & services → Application Credentials → HealthPlanet for Home Assistant**.

Client ID / Client Secret are application credentials—not a HealthPlanet Website login and password.

| Credential | Purpose | Scope |
| --- | --- | --- |
| Client ID | HealthPlanet API application | Shared by one HA installation |
| Client Secret | HealthPlanet API application | Shared by one HA installation |
| OAuth access token | Official API account authorization | One per family member |
| Website login ID | Experimental Website source | One per family member |
| Website password | Experimental Website source | One per family member |

## Add the first family member

1. Add **HealthPlanet for Home Assistant** and enter the family member name.
2. Select the shared Application Credential.
3. Open the HealthPlanet authorization link. It uses `https://www.healthplanet.jp/success.html`, not a My Home Assistant callback.
4. Approve access, copy the one-time code, and paste it into Home Assistant within 10 minutes.
5. Enter that member's separate HealthPlanet Website credentials and accept the experimental-source warnings.

The authorization code exists in memory only during exchange. It is never logged, written to disk, added to diagnostics, or saved in the config entry. The Client Secret stays in Home Assistant Application Credentials; only the per-member access token is copied into the entry. HealthPlanet documents no refresh-token grant, so official authentication failures start Reauth and require a new one-time code.

## Add another family member

Add the integration again, choose a different family-member name, reuse the same Application Credential, and authorize the other HealthPlanet account. Different Website accounts are allowed; the same Website login cannot create duplicate entries. Plaintext login IDs are never used in unique IDs, entity IDs, or logs.

Devices are named `HealthPlanet - {family member}`. Entity unique IDs remain `{entry_id}_{kind}`.

## Historical data

- Official metrics: up to 90 days per sync using documented `date=1`, `from`, and `to` parameters.
- Website supplementary metrics: the confirmed 31-day range only.
- Initial setup performs a history sync; daily refreshes are incremental in memory, and the **Sync history** button re-fetches both sources.
- `measurement_time` on each current sensor is the exact provider measurement timestamp.
- Home Assistant owns state `last_updated`; the integration never changes it or writes directly to Recorder tables.
- Recorder's supported external statistics import is hourly. Multiple measurements in one UTC hour produce arithmetic `mean`, `min`, and `max`; it does not pretend to provide exact-minute native state history.
- Repeated setup, reload, refresh, or manual sync is idempotent through stable source/kind/time identities and Recorder's update-by-hour import behavior. No duplicate history JSON is stored in `.storage`.

History import is a separate failure domain: Recorder or history-provider failures never make current sensors unavailable.

## Legacy v0.1.x entries

Existing Website-only, Official-only, and Hybrid entries continue to run after migration. They are not automatically converted because authorization requires interaction. **Reconfigure** upgrades Website-only or Official-only in place, preserves the other source's credentials, and keeps all existing entity unique IDs.

## Privacy

Diagnostics include source outcomes, structural row counts, safe sync counters, and sync execution time. They exclude family-member names, login IDs, credentials, authorization codes, tokens, health values, measurement timestamps, URLs with queries, and raw provider responses. See [Privacy](docs/PRIVACY.md) and [Security](SECURITY.md).

## Troubleshooting

- Authorization does not return to HA: this is expected; copy the code from HealthPlanet's success page back into the open HA form.
- Authorization code expired or invalid: generate another code and submit it within 10 minutes.
- Missing Application Credentials: finish the [API application guide](docs/HEALTHPLANET_API_SETUP.md) once for this HA.
- Official unavailable: use Reauth; Website complementary sensors remain independent.
- Website unavailable: check Website credentials; official sensors remain independent.
- Historical sync failed: current sensors continue; retry with the device's **Sync history** button.
- HA integration icon missing: restart after installing the complete v0.2.1 component, including `brand/`.
- HACS repository list still shows a placeholder: HA local integration branding and the HACS repository-list brand proxy are separate paths; this can be a HACS frontend limitation.

See [Troubleshooting](docs/TROUBLESHOOTING.md) and [Architecture](docs/ARCHITECTURE.md) for more detail.

## Maintainer release process

1. Update the manifest, `VERSION`, `USER_AGENT`, changelog, and documentation.
2. Run the full local validation suite, push `main`, and wait for Tests, HACS, and Hassfest.
3. Create and push an annotated stable semantic-version tag such as `v0.2.1`.
4. GitHub Actions revalidates version consistency, tests, coverage, privacy, HACS, and Hassfest before automatically publishing the stable GitHub Release.
5. HACS detects the published release through its normal background refresh.

No Personal Access Token is required. Release automation uses only the repository-scoped `GITHUB_TOKEN` supplied inside GitHub Actions.

## Trademark notice

TANITA and HealthPlanet are trademarks, service names, or brands of their respective owners.

Their names are used in this project only to identify compatibility with the corresponding service.

This project is an independent, unofficial open-source integration and is not affiliated with, not endorsed by, not sponsored by, and not officially supported by TANITA Corporation or TANITA Health Link.
