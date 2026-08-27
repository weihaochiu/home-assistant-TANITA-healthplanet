# Privacy

Health measurements and credentials stay inside the Home Assistant runtime and config-entry store. The integration does not create raw HTML, JSON, HAR, cookie, token, or measurement files.

Official diagnostics are split into `innerscan` and `sphygmomanometer` structural status. Website diagnostics contain a `per_kind` list. Allowed fields are source/mode, configured interval, success state, kind or endpoint, outcome, HTTP status, response category, backend code, fixed parser error identifier, row/record count, tag availability, timestamp-parsing success, and whether a complete blood-pressure pair was found.

Diagnostics and logs never include account identifiers, passwords, client secrets, authorization codes, access/refresh tokens, Cookie or Set-Cookie headers, CSRF fields, Authorization headers, request/response bodies, secret-bearing URLs, measurement values, measurement timestamps, or tracebacks containing payloads. Repeated identical source/kind warnings are suppressed until the outcome recovers.

Home Assistant Application Credentials stores the shared OAuth Client ID and Client Secret. Each config entry stores only that family member's access token plus its Website login ID and password because restart and session-expiry recovery otherwise cannot work. One-time authorization codes, Website cookies, and CSRF fields exist only in memory and are cleared after use or unload. `.storage` is not a dedicated encrypted password vault. Protect the Home Assistant configuration directory and backups, restrict host access, and avoid third-party backup destinations you do not trust.

To remove integration data, delete all **HealthPlanet for Home Assistant** config entries, uninstall the custom integration, and restart Home Assistant. Revoke the HealthPlanet OAuth grant and change the Website password if a host or backup may have been exposed.

Never attach unredacted diagnostics, credentials, raw requests/responses, screenshots containing account data, or real health data to a GitHub issue. Reproduce problems with synthetic values and timestamps only.
