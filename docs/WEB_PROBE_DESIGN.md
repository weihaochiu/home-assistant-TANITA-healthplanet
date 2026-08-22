# HealthPlanet web schema probe design

Research date: 2026-08-22 (UTC+08:00)

## Purpose and status

This repository is in an endpoint-research phase. The probe determines the current
normal website login form shape and returns only a sanitized schema description of
responses from the website's graph endpoint. It is not a HACS integration and it
does not establish that the endpoint is stable, supported, or suitable for medical
use.

## Public sources

- [HealthPlanet API specification](https://www.healthplanet.jp/apis/api.html),
  accessed 2026-08-22. The official document describes OAuth 2.0 and the documented
  `/status/innerscan`, `/status/sphygmomanometer`, and `/status/pedometer` APIs. It
  does not document `/graph/graph.json`.
- [Third-party graph endpoint research](https://pc.atsuhiro-me.net/entry/2023/07/22/195837),
  published 2023-07-22 and accessed 2026-08-22. This article reports that the
  website's authenticated graph view used `/graph/graph.json` and lists candidate
  kinds 1, 2, 3, 4, 5, 6, 7, 14, 22, and 23. The article explicitly describes the
  method as unofficial and potentially subject to change.
- Candidate endpoint: `https://www.healthplanet.jp/graph/graph.json`.

The graph endpoint is an undocumented internal web interface. It must never be
described as an official HealthPlanet API.

## Known candidate kind mapping

| Kind | Publicly reported meaning |
| ---: | --- |
| 1 | Weight |
| 2 | Body fat percentage |
| 3 | Body fat mass |
| 4 | Visceral fat level |
| 5 | Basal metabolic rate |
| 6 | Muscle mass |
| 7 | Estimated bone mass |
| 14 | Metabolic age |
| 22 | Total body water percentage |
| 23 | Whole-body muscle quality score |

The list is a third-party observation, not an exhaustive or official mapping.

## Unknown `code=-1`

A user manually observed `{"code":[-1]}` from a combined URL before this work.
There is no cited official definition for `-1`; the probe and documentation do not
interpret it as "no data." Plausible but unconfirmed causes include authentication
state, a rejected kind or kind combination, changed parameters, an internal
validation failure, or endpoint/schema drift. These are hypotheses only.

## Login and request architecture

The user runs the script locally and types the login ID with `input()` and the
password with `getpass()`. The program performs one GET of the official login page,
parses exactly one normal POST form containing a login field and password field,
copies hidden fields, and submits only those fields plus the entered credentials.
Both form action and every redirect must remain HTTPS on `www.healthplanet.jp`.

Authentication success requires more than HTTP 200: the final path must not be a
login path, the returned page must not contain a password form, and it must contain
a logout marker. An unfamiliar flow stops safely.

After authentication, kind 1 is requested alone. Only when kind 1 is recognized as
normal JSON with an available or empty data container are the remaining kinds
requested once each, sequentially, with 0.75 seconds between requests. The hard
upper bound is 12 HTTP requests per run: login GET, login POST, and ten kind GETs.
There are no automatic retries or parallel requests.

## Manual-interaction stop

CAPTCHA, reCAPTCHA, hCaptcha, Cloudflare/bot verification, MFA/OTP, consent controls,
security warnings, multiple/unknown login forms, and other unfamiliar login flows
produce `MANUAL_INTERACTION_REQUIRED`. The script does not fill, guess, simulate,
or bypass these controls.

## Privacy and output contract

Cookies exist only in an in-memory `CookieJar`; they are never serialized and are
cleared before process exit. Credential-bearing references are released, the HTTP
session is closed, and no raw response dump, cookie dump, diagnostics bundle, or
log file is created.

`_local_only/healthplanet_schema_probe.json` is rebuilt from an explicit output
allowlist. It may contain response status, media type, JSON/schema recognition,
safe key names, non-sensitive error codes, record count, and abstract timestamp
formats. It cannot contain the raw JSON or measurement values. Redirects are stored
as paths without query strings. Suspicious or personal-data-like field names are
dropped. `_local_only/` is excluded from Git and source backups.

The terminal prints only login state, one short status per tested kind, and the
sanitized output path. Users must not share credentials or full raw responses with
Codex. The endpoint may change without notice, and users are responsible for
reviewing applicable service terms.

