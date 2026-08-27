# Architecture

One Home Assistant config entry owns one family-member device and two independent source coordinators for new Hybrid setups. Entity unique IDs remain `{entry_id}_{metric_kind}`, preserving v0.1.x identities. Hybrid creates no duplicate weight/body-fat entities. Official-only and Website-only remain internal compatibility modes for migration, reauth, recovery, and in-place upgrade.

| Mode | Official coordinator | Website coordinator | Sensors |
| --- | --- | --- | --- |
| Hybrid | Kinds 1, 2, 101, 102, 103 | Kinds 3, 4, 5, 6, 7, 14, 22, 23 | 13 |
| Official-only | Kinds 1, 2, 101, 102, 103 | — | 5 |
| Website-only | — | Kinds 1, 2, 3, 4, 5, 6, 7, 14, 22, 23 | 10 |

The Official provider uses one Home Assistant Application Credential shared by family-member entries. Authorization uses scope `innerscan,sphygmomanometer`, fixed redirect URI `https://www.healthplanet.jp/success.html`, and a copied one-time code. It never uses My Home Assistant's state callback. The code exists only in flow memory; the Client Secret remains in Application Credentials and only the member's access token is copied into the config entry. HealthPlanet documents no refresh grant, so a rejected token starts manual-code reauthentication.

Sphygmomanometer records are grouped by their parsed JST timestamp. The parser selects the latest group with both systolic (`622E`) and diastolic (`622F`) values. Pulse (`6230`) is emitted only if it belongs to that same group. An incomplete newer group is ignored in favour of the latest complete pair.

The Website provider owns a dedicated in-memory cookie jar, discovers the login form and CSRF field without persisting page content, and sequentially requests only its mode's allowlisted graph kinds. It rejects cross-origin actions, challenges, HTML responses, unknown schemas, and unsupported backend codes. One controlled relogin is allowed after session expiry. Production never imports `research/`.

Each coordinator has its own interval, `last_update_success`, data snapshot, warning suppression, and auth callback. Successful data from one source remains available when the other source fails. Null kind 23 is not an overall failure. If every primary kind or every official endpoint fails, only that source's coordinator update fails. Authentication errors are never downgraded to parser or per-kind errors.

Website rows accept the researched two-field schema without assuming value/timestamp order. Official fields remain tag-based. Website and Official timestamps are interpreted as Asia/Tokyo and converted to timezone-aware UTC. Parsers emit immutable, sorted, deduplicated history per kind plus each latest `Measurement`; sensors never inspect raw payloads.

History synchronization is separate from current coordinators. Official history is bounded to 90 days and Website history to the confirmed 31 days. Exact provider timestamps appear as `measurement_time`; Recorder import groups them into supported hourly external statistics with arithmetic mean/min/max, explicit `StatisticMeanType.ARITHMETIC`, `has_sum=False`, and explicit `unit_class`. Stable entry/kind/time/source identity and Recorder's update-by-hour API make repeat sync idempotent. The integration never manipulates Recorder tables or stores duplicate history JSON.

Native Safe Update is a separate integration-management layer and never imports or mutates either data coordinator. The oldest config entry by persisted `created_at` (with `entry_id` as a tie-breaker) owns one repository-management button; ownership is handed to the next entry when that entry is removed. All entries share one `SafeUpdateManager` and one `asyncio.Lock` through domain-level runtime data.

The manager uses only Home Assistant public registries, entity states, and services. It identifies the HACS update entity by the exact repository URL exposed by the public update entity, with HACS device metadata and an Options-stored registry `unique_id` as fallbacks. It observes the automatic-backup event entity before invoking `backup.create_automatic`, requires a new `in_progress` event followed by a new `completed` event, installs the captured target through `update.install`, and requires the final installed version before optionally calling `homeassistant.restart`. Every failure path is fail-closed: backup failure prevents install, update failure prevents restart, and HACS absence does not affect health-data setup.
