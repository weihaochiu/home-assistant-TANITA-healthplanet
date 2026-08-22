# Authenticated HealthPlanet website research

## Authorization and boundaries

This study was performed on 2026-08-22 with the user's explicit authorization to
use their own temporary HealthPlanet credentials. The probe used only
`https://www.healthplanet.jp`, did not bypass access controls, did not modify
health data or account settings, and did not test vulnerabilities. Two login
sessions were used, each with 12 sequential requests and at least one second
between request starts. The combined 24 requests remained below the limit of 50.

No CAPTCHA, MFA, OTP, consent challenge, Cloudflare challenge, 401, 403, 429, or
5xx retry was encountered.

## Authentication findings

- Login page and form action: `/login.do`
- Method: `POST`
- Login field: `loginId`
- Password field: `passwd`
- Hidden fields: `org.apache.struts.taglib.html.TOKEN`, `send`, and `url`
- CSRF: the Struts token is required by the observed form
- Encoding: UTF-8
- Successful destination: `/index.do`
- Session: authenticated Cookie session; values and names were not persisted
- Success evidence: non-login destination, logout marker, and session Cookie

## Endpoint findings

The confirmed website request is:

```text
GET /graph/graph.json?day=31&page=1&kind=<allowlisted-kind>
```

Parameter names are `day`, `page`, and `kind`. Every tested kind returned HTTP
200 with `application/json`, `code` shaped as `list[int]`, and `code=[0]` during
the authenticated research. The top-level schema includes `value1`,
`value1_unit`, range metadata, and display-format metadata. Non-null `value1`
records use a two-element shape containing one number and one string.

An earlier unauthenticated/direct-browser observation returned `{"code":[-1]}`.
The service does not define that code publicly in the material used for this
study, so this project does not assign it a meaning. The parser treats it as a
distinct backend error, never as an empty dataset.

Because the known graph endpoint worked after normal login, no endpoint guessing,
first-party JavaScript discovery, or browser network interception was needed.

## Sanitized metric evidence

| Metric | Kind | Unit returned | Live non-null rows | Parser | Confidence |
|---|---:|---|---:|---|---|
| Weight | 1 | kg | 7 | Ready | High |
| Body-fat percentage | 2 | % | 7 | Ready | High |
| Body-fat mass | 3 | kg | 7 | Ready | High |
| Visceral-fat level | 4 | none | 7 | Ready | High |
| Basal metabolic rate | 5 | kcal | 7 | Ready | High |
| Muscle mass | 6 | kg | 7 | Ready | High |
| Estimated bone mass | 7 | kg | 7 | Ready | High |
| Metabolic age | 14 | 才 | 7 | Ready | High |
| Body-water percentage | 22 | % | 7 | Ready | High |
| Muscle-quality score | 23 | none | 0; one null item | Ready for non-null data | Medium |

The probe deliberately did not persist timestamps or measurement values. The
offline parser accepts the confirmed number-plus-string record shape and handles
12- and 14-digit timestamps, ISO 8601, common slash/dash website formats, Unix
seconds, and Unix milliseconds. This should be verified again during any future
opt-in integration work without increasing the scope of this research.

## Decision

**RESULT A — complete composition data is available.** Normal login succeeded,
the GET endpoint was reproducible, multiple metrics beyond weight and body fat
were present, and the offline parser passed its synthetic tests without bypassing
any security mechanism.

This is evidence of current website behavior, not a stability guarantee or an
official API contract.
