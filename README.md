# TANITA HealthPlanet for Home Assistant

Development branch for a HACS-compatible Home Assistant custom integration. Version 0.1.0 supports multiple independent config entries and makes the documented HealthPlanet OAuth API the default provider.

## Providers

| Provider | Status | Authentication | Sensors |
| --- | --- | --- | --- |
| Official API | Recommended | OAuth `client_id`, `client_secret`, authorization code | Weight, body-fat percentage |
| Experimental Website | Disabled by default; explicit opt-in | HealthPlanet website login | All 10 researched metrics |

The website provider uses an authenticated, undocumented website endpoint. It is **not** an official API, may change or be blocked without notice, and is not guaranteed or supported by TANITA. Each config entry uses exactly one provider; sources are never merged.

## Sensors

The website provider exposes weight, body-fat percentage, body-fat mass, visceral-fat level, basal metabolic rate (`kcal/day`), muscle mass, estimated bone mass, metabolic age, body-water percentage, and muscle-quality score. The official provider exposes only its documented weight and body-fat tags. Missing values stay unavailable and are never replaced with zero. Muscle quality remains experimental/medium-confidence until a real non-null value is independently validated.

## Development installation

No release or tag has been created. For branch testing, add this repository to HACS as a custom Integration repository, or copy `custom_components/tanita_healthplanet` into Home Assistant's `custom_components` directory. Restart Home Assistant, then use **Settings → Devices & services → Add integration → TANITA HealthPlanet**.

The official flow requires credentials from HealthPlanet's API registration. The experimental flow requires two confirmations: the endpoint is unofficial, and Home Assistant's `.storage` is not a dedicated encrypted password vault.

## Operation and removal

Polling defaults to 60 minutes and can be changed to 30–1440 minutes in Options. Authentication failures start Home Assistant reauthentication. Removing a config entry unloads its entities, clears its in-memory cookies/session, and removes its stored entry data through Home Assistant. To remove the code, uninstall the custom repository in HACS after removing all entries.

Never paste credentials, unredacted diagnostics, cookies, tokens, or real health values into an issue. Health data is not medical advice. See [Privacy](docs/PRIVACY.md), [Security](SECURITY.md), [Architecture](docs/ARCHITECTURE.md), and [Troubleshooting](docs/TROUBLESHOOTING.md).
