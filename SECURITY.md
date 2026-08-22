# Security policy

Do not open a public issue containing a login ID, password, OAuth client secret, authorization code, access token, cookie, CSRF token, unredacted diagnostics, raw HealthPlanet response, or real health measurement. Revoke or change exposed credentials before reporting a security bug.

The official provider stores the OAuth client data and access token in the Home Assistant config entry. The experimental provider stores the website login in the config entry so it can recover after restart or session expiry. Home Assistant's `.storage` is access-controlled application storage, not a dedicated encrypted password vault. Secure the host, backups, and Home Assistant account accordingly.

The integration does not log credentials, include them in diagnostics or entities, or persist cookies, CSRF fields, raw HTML, or raw JSON. Website session state is held in memory and cleared on unload/removal. Repository CI scans the working tree, all reachable Git blobs, and retained source backups for credential/privacy risks.

See `docs/SECURITY.md` for the research-specific policy retained from the authenticated study.
