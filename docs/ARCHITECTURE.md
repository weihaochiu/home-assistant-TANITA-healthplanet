# Architecture

One Home Assistant config entry owns one device and either one or two independent source coordinators. Entity unique IDs remain `{entry_id}_{metric_kind}`, preserving the v1 Website entity identities. Hybrid creates no duplicate weight/body-fat entities.

| Mode | Official coordinator | Website coordinator | Sensors |
| --- | --- | --- | --- |
| Hybrid | Kinds 1, 2, 101, 102, 103 | Kinds 3, 4, 5, 6, 7, 14, 22, 23 | 13 |
| Official-only | Kinds 1, 2, 101, 102, 103 | — | 5 |
| Website-only | — | Kinds 1, 2, 3, 4, 5, 6, 7, 14, 22, 23 | 10 |

The Official provider uses Home Assistant's Application Credentials and external OAuth flow with scope `innerscan,sphygmomanometer`. Each update calls the documented Innerscan and Sphygmomanometer endpoints at most once. Their structural outcomes are independent, so one endpoint can succeed while the other fails. HealthPlanet documents only the authorization-code token grant; the integration does not invent a refresh grant. A rejected token starts Home Assistant reauthentication.

Sphygmomanometer records are grouped by their parsed JST timestamp. The parser selects the latest group with both systolic (`622E`) and diastolic (`622F`) values. Pulse (`6230`) is emitted only if it belongs to that same group. An incomplete newer group is ignored in favour of the latest complete pair.

The Website provider owns a dedicated in-memory cookie jar, discovers the login form and CSRF field without persisting page content, and sequentially requests only its mode's allowlisted graph kinds. It rejects cross-origin actions, challenges, HTML responses, unknown schemas, and unsupported backend codes. One controlled relogin is allowed after session expiry. Production never imports `research/`.

Each coordinator has its own interval, `last_update_success`, data snapshot, warning suppression, and auth callback. Successful data from one source remains available when the other source fails. Null kind 23 is not an overall failure. If every primary kind or every official endpoint fails, only that source's coordinator update fails. Authentication errors are never downgraded to parser or per-kind errors.

Website rows accept the researched two-field schema without assuming value/timestamp order. Official fields remain tag-based. Website and Official timestamps are interpreted as Asia/Tokyo and converted to timezone-aware UTC. Parsers emit only normalized `Measurement` objects; sensors never inspect raw payloads.
