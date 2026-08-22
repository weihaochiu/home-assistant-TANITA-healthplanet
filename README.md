# home-assistant-TANITA-healthplanet

Research repository for a possible Home Assistant integration with TANITA
HealthPlanet.

The official HealthPlanet API is the recommended production path and formally
exposes weight and body-fat data. An authorized, low-frequency study of one
user's own account on 2026-08-22 also confirmed that the authenticated website
currently exposes additional body-composition metrics through an internal graph
endpoint. That endpoint is not an official API and may change without notice.

## Confirmed research result

`GET /graph/graph.json` with the authenticated website session returned schemas
for weight, body-fat percentage, body-fat mass, visceral-fat level, basal
metabolic rate, muscle mass, estimated bone mass, metabolic age, body-water
percentage, and muscle-quality score. No real health value, credential, Cookie,
token, account identifier, or raw response is stored in Git.

The reusable code under `research/healthplanet_web/` is experimental and is not
a released Home Assistant provider. It uses synthetic fixtures for offline
tests. See [Authenticated research](docs/AUTHENTICATED_RESEARCH.md),
[experimental provider](docs/EXPERIMENTAL_PROVIDER.md), and
[security guidance](docs/SECURITY.md).

## Status

- Research decision: **RESULT A — complete composition data is available**.
- Production recommendation: build the official OAuth provider first.
- Optional next step: add the authenticated website provider behind an explicit
  experimental opt-in.
- No release, HACS package, merge, or production claim is included in this
  research branch.

HealthPlanet data must not be used for medical diagnosis or treatment decisions.
Users are responsible for reviewing the service terms before enabling an
experimental website provider.
