# HealthPlanet web endpoint research probe

This repository currently contains a privacy-safe research probe for TANITA
HealthPlanet's website. It is **not a completed Home Assistant or HACS integration**.
The goal of this phase is to let the account owner determine the current normal
login flow, whether the website's undocumented graph endpoint still responds, and
which candidate body-composition kinds produce recognizable schemas.

## Safety boundaries

- Never give your HealthPlanet password to Codex or paste it into a chat.
- Run the probe yourself in a local terminal. The login ID is entered with normal
  terminal input and the password is entered with Python `getpass`, so the password
  is not displayed.
- Credentials are never accepted as command-line arguments or read from `.env` or
  credential files.
- Cookies live only in an in-memory cookie jar and are cleared when the process
  exits. No cookie, token, HAR, or raw response dump is created.
- No health measurement value is written to disk. The saved JSON is rebuilt from a
  strict schema allowlist.
- CAPTCHA, MFA/OTP, consent controls, bot challenges, security warnings, cross-host
  redirects, and unfamiliar login flows stop with `MANUAL_INTERACTION_REQUIRED`.
  The probe does not try to bypass them.
- Requests are sequential, have a 15-second timeout, are never retried, and have a
  hard upper bound of 12 per run.

The graph endpoint is an undocumented internal website interface, not an official
HealthPlanet API, and may change or disappear without notice. A manually observed
`code=-1` has no cited official definition and is not assumed to mean "no data."
This tool is not for medical decisions. Review HealthPlanet's current terms and
decide whether the probe is appropriate for your account.

## Run locally

The probe has no third-party runtime dependency. From PowerShell:

```powershell
cd D:\Github\home-assistant-TANITA-healthplanet
py scripts\probe_healthplanet.py
```

Optionally use an isolated environment:

```powershell
cd D:\Github\home-assistant-TANITA-healthplanet
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements_probe.txt
py scripts\probe_healthplanet.py
```

The sanitized result is written to
`_local_only/healthplanet_schema_probe.json`. The entire `_local_only/` directory is
excluded from Git and source backups. Do not share your password or a full raw
website response. After the probe, tell Codex only:

> Probe completed. Read `_local_only/healthplanet_schema_probe.json` and continue
> the analysis.

## Development and verification

All repository tests are offline and use synthetic fixtures only:

```powershell
python -m compileall scripts tests
python -m pytest
```

See [the design document](docs/WEB_PROBE_DESIGN.md) for sources, request flow,
privacy controls, output rules, and the unknown status of `code=-1`.
