# Troubleshooting

## Reauthentication requested

Open the integration's reauthentication notification. Official reauthentication uses the standard external OAuth flow and requires the `innerscan,sphygmomanometer` scope. Website reauthentication asks only for new website credentials. In Hybrid mode the failing source is repaired without clearing the other source's credentials or data; when both sources require reauthentication, Official OAuth is completed first and Website follows.

## One source or sensor is unavailable

Official and Website coordinators fail independently. Inspect the redacted diagnostics for `official.innerscan`, `official.sphygmomanometer`, or `website.per_kind`. Missing/null data stays unavailable and never becomes zero. Kind 23 may legitimately be null without affecting other kinds.

Blood-pressure sensors need an exact-timestamp systolic/diastolic pair. Pulse also needs that same timestamp. A newer incomplete group is intentionally ignored; if no complete pair exists, all blood-pressure values remain unavailable.

## Website source stopped working

The website endpoint is unofficial and may change or disappear without warning. A challenge/MFA page, changed login form, HTML graph response, or blocked automation triggers a controlled error or reauthentication. Complete any legitimate manual account action on the official site yourself, then retry later; do not bypass challenges. Do not increase polling frequency: the minimum is 30 minutes and the default is 60.

## Upgrade this development candidate

Download the target branch ZIP and replace the entire `custom_components/tanita_healthplanet` directory. Restart Home Assistant. Existing v1 Website entries migrate to Website-only without password re-entry; use Reconfigure to upgrade to Hybrid. Existing Official entries need reauthentication to grant the new sphygmomanometer scope.

## Reporting a problem

Share only redacted diagnostics. Never post credentials, client secrets, OAuth codes/tokens, Cookie/Set-Cookie, CSRF tokens, raw HTML/JSON, request/response bodies, health values, measurement timestamps, or screenshots that reveal them. GitHub issues are public unless the repository explicitly says otherwise.

## Removing the integration

Remove all config entries under Devices & services, uninstall the repository through HACS, and restart Home Assistant. If exposure is suspected, also revoke the OAuth grant and change the website password.
