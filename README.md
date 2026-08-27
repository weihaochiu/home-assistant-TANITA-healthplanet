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
- HA integration icon missing: restart after installing the complete v0.2.0 component, including `brand/`.
- HACS repository list still shows a placeholder: HA local integration branding and the HACS repository-list brand proxy are separate paths; this can be a HACS frontend limitation.

See [Troubleshooting](docs/TROUBLESHOOTING.md) and [Architecture](docs/ARCHITECTURE.md) for more detail.

## Trademark notice

TANITA and HealthPlanet are trademarks, service names, or brands of their respective owners.

Their names are used in this project only to identify compatibility with the corresponding service.

This project is an independent, unofficial open-source integration and is not affiliated with, not endorsed by, not sponsored by, and not officially supported by TANITA Corporation or TANITA Health Link.
