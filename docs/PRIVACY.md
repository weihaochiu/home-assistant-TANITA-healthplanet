# Privacy

Health measurements and credentials stay inside the Home Assistant runtime and config-entry store. The integration exposes only the latest metric state; it does not create raw-response files. Its diagnostics contain provider type, update interval, success state, available/error kind numbers, and privacy-safe per-kind structural outcomes. These outcomes may include HTTP status, content category, backend code, fixed parser error ID, row count, and whether timestamp parsing succeeded. They never include response bodies, measurement values or timestamps, account identifiers, credentials, cookies, CSRF fields, authorization headers, tokens, request bodies, or secret-bearing URLs.

The official provider stores OAuth client data and its access token. The website provider stores the login ID and password because restart/session-expiry recovery otherwise cannot work. `.storage` is not a dedicated encrypted password vault. Protect Home Assistant configuration backups and limit host access. Cookies and CSRF fields exist only in memory and are cleared when the entry unloads.

To remove stored data, delete every TANITA HealthPlanet config entry in Home Assistant. Then remove the custom integration through HACS or delete its component directory and restart. Revoke the OAuth grant or change the website password if you no longer trust a host or backup.

Never attach unredacted diagnostics, credentials, raw requests/responses, or real health data to an issue. Use synthetic values and timestamps only.
