# Troubleshooting

## Reauthentication requested

Open the integration's reauthentication notification. Official entries require a new authorization code; website entries require the login ID and password again. Sensitive fields are never prefilled in Options. Repeated website failures may mean the page changed, a challenge/MFA step appeared, or automated access was blocked. Complete manual account actions on the official site, then retry later; do not bypass challenges.

Website diagnostics expose a `per_kind` list containing only structural fields such as `kind`, `outcome`, `http_status`, `content_category`, `backend_code`, `error_id`, `row_count`, and `timestamp_parsing_success`. Share only redacted diagnostics. Never share credentials, cookies, CSRF tokens, raw responses, health values, or measurement timestamps.

## A sensor is unavailable

Unavailable is intentional for empty/null data and is never converted to zero. If only one website metric is unavailable, other metrics continue updating. Kind 23 is experimental and may legitimately remain null. Check Home Assistant's redacted integration error and the safe diagnostics kind lists.

## Website provider stopped working

The website endpoint is unofficial and may change or disappear without warning; TANITA does not guarantee support. Prefer the Official API provider when weight and body-fat percentage are enough. Do not increase polling frequency: the minimum option is 30 minutes and the default is 60 minutes.

## Removing the integration

Remove all config entries under Devices & services, uninstall the custom repository in HACS, and restart Home Assistant. If exposure is suspected, also revoke the OAuth grant or change the website password. Do not post credentials, unredacted diagnostics, or real measurements in an issue.
