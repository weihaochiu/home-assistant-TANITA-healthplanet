# Experimental website provider

## Scope

`research/healthplanet_web/` contains a typed parser and a small experimental
client for the authenticated website graph response. HTTP/session handling,
login, models, constants, errors, and parsing are separated. It is intentionally
outside a production Home Assistant custom component.

`Measurement` contains:

- `metric_key`
- `value`
- `unit`
- `measured_at`
- `source`
- `model`
- `experimental`
- `raw_kind`

Only the ten kinds confirmed in the authenticated study are mapped. Unknown
kinds raise a fixed safe error. Unknown schema fields are returned only as
sanitized key names and never become Home Assistant sensors automatically.

## Parser behavior

The parser supports null, `-`, empty strings, numeric strings, integers, floating
point numbers, multiple timestamp formats, timezone-aware datetimes, empty data,
newest-record selection, unknown kinds, schema drift, `code=-1`, malformed
responses, HTML login pages, and expired sessions. Synthetic fixtures model the
observed `value1` number-plus-string row shape without copying a live response.

## Stability and privacy

`/graph/graph.json` is an internal website endpoint, not the official
HealthPlanet API. Login fields, CSRF handling, Cookie behavior, kind mappings, and
response schema can change without notice. A production implementation would
need conservative failure handling, a strict request budget, no automatic sensor
creation for new fields, and explicit user opt-in.

The experimental provider must never log credentials, form bodies, Cookies,
tokens, full redirect queries, raw responses, or health values. It must not write
session state to Home Assistant diagnostics or backups.

## Home Assistant feasibility

The current endpoint is technically reproducible with a normal authenticated
session and can supply additional body-composition entities. The primary HACS
provider should nevertheless use official OAuth for stability and supportability.
The website provider may be considered later as a disabled-by-default,
experimental alternative with prominent warnings and separate tests.
