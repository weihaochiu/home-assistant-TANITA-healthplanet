# Security and privacy

## Credential handling

Local research credentials are read only from `.env.local` inside the Python
process. The file is ignored by Git and excluded from source backups. Credentials
must never appear in commands, logs, exceptions, fixtures, reports, Git objects,
or ZIP archives. `.env.example` contains empty placeholders only.

The research session closes its HTTP opener, clears its in-memory Cookie jar, and
drops password/login references on every exit path. No Cookie, token, raw HTML,
raw JSON, HAR, or session file is required or retained.

## Repository controls

- `_local_only/` is ignored and excluded from backups.
- `BACKUP/*.zip` is ignored.
- The pre-push hook runs `scripts/create_backup.py` and blocks the push on failure.
- Backups exclude Git metadata, local research data, environment files, secrets,
  Cookies, sessions, tokens, HAR, raw responses, logs, caches, and virtual
  environments.
- Backup retention is limited to the newest ten ZIP files.
- Only synthetic fixtures may be tracked.

## Runtime controls

The research probe permits HTTPS requests only to `www.healthplanet.jp`, rejects
cross-host redirects, permits POST only for login, and rejects DELETE, PUT, and
PATCH. It is sequential, waits at least one second between request starts, caps a
run at 50 requests and two login posts, stops immediately on 401, 403, or 429,
retries a 5xx response at most once, and never retries timeouts.

Do not use this project to bypass CAPTCHA, MFA, bot protection, consent, access
controls, or account restrictions. Do not use it to modify health data or account
settings, scan endpoints, inspect another user's traffic, or test vulnerabilities.

## User responsibilities

The website endpoint is unofficial. Users must evaluate the HealthPlanet terms
and privacy impact themselves. Health measurements are not medical advice and
must not be used for diagnosis or treatment decisions.
