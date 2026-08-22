# Architecture

Each Home Assistant config entry owns one provider, one coordinator, and one device. Entry IDs are part of every entity unique ID, so multiple accounts remain isolated and reloads do not duplicate entities.

The official provider exchanges an authorization code for an access token and requests only the documented weight (`6021`) and body-fat (`6022`) tags. The experimental provider owns a dedicated cookie jar, discovers the login form and CSRF field in memory, and sequentially requests the ten allowlisted graph kinds. It rejects cross-origin actions, challenges, HTML responses, unknown schemas, and unsupported backend codes.

`DataUpdateCoordinator` polls every 60 minutes by default. A website update reuses one authenticated session, serializes concurrent calls, spaces requests, and permits one controlled login after an expired session. One kind may be null or fail schema validation without hiding successful kinds. Authentication failures become Home Assistant reauthentication; transient/rate failures become `UpdateFailed` and naturally wait for the next conservative coordinator cycle.

Production runtime never imports `research/`. Parsers use confirmed positional or documented named fields, interpret website timestamps as JST, and convert them to timezone-aware UTC values.
