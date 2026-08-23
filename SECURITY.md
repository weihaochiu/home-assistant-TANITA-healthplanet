# Security policy

Do not open a public issue containing a login ID, password, OAuth client secret, authorization code, access token, cookie, CSRF token, unredacted diagnostics, raw HealthPlanet response, or real health measurement. Revoke or change exposed credentials before reporting a security bug.

Home Assistant Application Credentials stores the official OAuth client data, and the integration config entry stores the resulting token. The experimental provider stores the website login in the config entry so it can recover after restart or session expiry. Home Assistant's `.storage` is access-controlled application storage, not a dedicated encrypted password vault. Secure the host, backups, and Home Assistant account accordingly.

The integration does not log credentials, include them in diagnostics or entities, or persist cookies, CSRF fields, raw HTML, or raw JSON. Website session state is held in memory and cleared on unload/removal. Repository CI scans the working tree, all reachable Git blobs, and retained source backups for credential/privacy risks.

The two runtime sources have separate sessions, coordinators, authentication handling, and diagnostics. A failure or reauthentication request for one source must not expose or clear credentials belonging to the other. See `docs/SECURITY.md` for repository and authenticated-research controls.
