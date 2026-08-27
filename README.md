# TANITA HealthPlanet for Home Assistant

Development candidate for a HACS-compatible Home Assistant custom integration. Version 0.1.0 uses an **official-first hybrid** architecture: documented HealthPlanet APIs own every metric they expose, while an explicitly enabled experimental website source fills only the remaining metrics.

## Installation

### Recommended: HACS

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=weihaochiu&repository=home-assistant-TANITA-healthplanet&category=integration)

Open this repository directly in HACS. Requires HACS to be installed and configured first.

1. Click the HACS button.
2. Download TANITA HealthPlanet in HACS.
3. Restart Home Assistant.
4. Click the Add Integration button below.

Don't have HACS yet?

[Install and configure HACS first](https://www.hacs.xyz/docs/use/download/download/), then return here and use the button above.

### Add the integration

After installing with HACS and restarting Home Assistant:

[![Add TANITA HealthPlanet to Home Assistant](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=tanita_healthplanet)

This button starts the TANITA HealthPlanet config flow under **Settings → Devices & services → Add Integration**. It does not install the Python component and works only after HACS has installed `custom_components/tanita_healthplanet` and Home Assistant has restarted.

### Alternative: Manual installation / development testing

For development, recovery, or debugging, use the ZIP and component-replacement procedure in [Manual installation and configuration](#manual-installation-and-configuration).

## Modes

| Mode | Status | Authentication | Sensors |
| --- | --- | --- | --- |
| Official-first Hybrid | Recommended/default | Home Assistant Application Credentials OAuth, then optional website login | 13 |
| Official API only | Supported | Home Assistant Application Credentials OAuth | 5 |
| Experimental Website only | Experimental | HealthPlanet website login | 10 |

Hybrid never reads weight or body-fat percentage from the website. Official endpoints provide weight, body-fat percentage, systolic and diastolic blood pressure, and pulse. The website source provides body-fat mass, visceral-fat level, basal metabolic rate (`kcal`), muscle mass, estimated bone mass, metabolic age, body-water percentage, and muscle-quality score.

Blood-pressure sensors require sphygmomanometer data in the HealthPlanet account. Values are published only from the latest timestamp containing both systolic and diastolic records. Pulse is included only when it has that same timestamp. An incomplete newer group does not replace the latest complete pair. Missing and null values stay unavailable and are never replaced with zero.

The website endpoint is authenticated but undocumented. It may change or be blocked without notice and is not guaranteed or supported by TANITA. Website-only mode exists for migration and troubleshooting; Hybrid is recommended.

## Manual installation and configuration

No release or tag has been created. To test this branch, download its ZIP and replace the entire `custom_components/tanita_healthplanet` folder in Home Assistant; do not mix files from older candidates. Restart Home Assistant, then use **Settings → Devices & services → Add integration → TANITA HealthPlanet**.

For Official or Hybrid mode, first add HealthPlanet under **Settings → Devices & services → Application Credentials** using the client ID and client secret from your HealthPlanet API application. Register this redirect URI with HealthPlanet:

`https://my.home-assistant.io/redirect/oauth`

The requested OAuth scope is `innerscan,sphygmomanometer`. Existing official entries created before this scope was added must complete reauthentication. Hybrid then offers an explicit website opt-in and displays both the unofficial-endpoint and `.storage` credential warnings before accepting website credentials.

Existing v1 website entries migrate in place to Website-only mode without changing entity unique IDs or asking for the password again. Use **Reconfigure** to upgrade one safely to Hybrid through the standard external OAuth flow. Separate Official and Website polling intervals default to 60 minutes and can each be set to 30–1440 minutes in Options.

## Failure isolation, privacy, and removal

Official Innerscan, Official Sphygmomanometer, and Website polling have structural diagnostics, and the two source coordinators have independent availability and authentication state. One source failing does not erase fresh data from the other. Source-specific authentication failures start reauthentication; ordinary repeated failures are warning-throttled until recovery.

Home Assistant stores OAuth data and, when enabled, website login credentials in the config-entry store. `.storage` is not a dedicated encrypted password vault. Never paste credentials, cookies, tokens, raw responses, unredacted diagnostics, or real health values into an issue.

To remove stored integration data, delete all TANITA HealthPlanet config entries, uninstall the custom repository through HACS (or delete its component folder), restart Home Assistant, and revoke the OAuth grant or change the website password if needed.

Before public HACS submission, the repository owner still needs to choose a license, add a GitHub description and valid topics, and provide brand assets. CI excludes only those owner-controlled publication checks.

See [Privacy](docs/PRIVACY.md), [Security](SECURITY.md), [Architecture](docs/ARCHITECTURE.md), and [Troubleshooting](docs/TROUBLESHOOTING.md).

To inspect diagnostics safely, open the integration's three-dot menu in Devices & services and select **Download diagnostics**. Review the file locally and redact it again before sharing; never attach it together with account screenshots or raw provider responses.
