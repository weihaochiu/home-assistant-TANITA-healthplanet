# Next steps

The authenticated study supports **RESULT A**, but this branch must stop before a
release or production integration.

Recommended next phase:

1. Build the official OAuth HealthPlanet provider for weight and body-fat data.
2. Design the website provider as an explicit, disabled-by-default experimental
   option rather than a replacement for the official provider.
3. Revalidate timestamp parsing with a privacy-safe structural test during that
   implementation; do not retain live values.
4. Add Home Assistant entities only for confirmed kinds and keep unknown fields
   out of the entity registry.
5. Add configuration-flow warnings about the internal endpoint, credentials,
   service terms, schema instability, and non-medical use.
6. Add bounded update intervals, session-expiry handling, diagnostics redaction,
   and reauthentication without retry storms.
7. Run Home Assistant, HACS, quality-scale, and CI tests in a separate branch.

Do not merge, tag a release, publish HACS artifacts, or claim production support
as part of this research phase.
