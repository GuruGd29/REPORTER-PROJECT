# Security policy

## Reporting a vulnerability

Please report security issues privately by emailing
`security@your-org.example` (or by using GitHub's "Report a
vulnerability" form on this repository's Security tab — preferred).

Do **not** open a public GitHub issue for security reports. We aim to
respond within 3 business days and to ship a patched release within
14 days of confirmed reports.

## Supported versions

| Version | Supported |
|---|---|
| 0.8.x | ✅ |
| 0.7.x | ✅ — critical fixes only |
| < 0.7 | ❌ |

## Threat model

qa-dashboard captures HTTP traffic and writes it to disk. The most
common security-relevant concerns are:

### 1. Sensitive data in captured network traffic

Captured request/response bodies and headers may contain credentials,
session tokens, PII, or other sensitive data. The dashboard exposes
this data in plain text in `tests/*.json` and in the rendered HTML.

**Mitigations available today:**

- **Redaction is on by default.** The following headers are redacted
  to `***` before being written to disk:
  - `authorization`
  - `cookie`
  - `set-cookie`
  - `x-api-key`
  - `x-auth-token`
  - `proxy-authorization`
- **Extend or replace** the redaction list with
  `--qa-dashboard-redact "header1,body_field,..."` or the
  `QA_DASHBOARD_REDACT` env var. Matches are case-insensitive
  substrings against header names and JSON body keys.
- **Limit capture scope** with `--qa-dashboard-host-filter
  api.your-domain.com` to only retain flows touching specific hosts.
- **Cap body size** — bodies over 100 KB are stored as
  `body_encoding: "omitted"` with no payload.

**Responsibilities you keep:**

- The redaction list is heuristic; review captures before sharing
  them externally.
- Run directories under `captures/` should be treated like any other
  build artifact and not be committed to public repos or uploaded
  unredacted to public dashboards.

### 2. mitmproxy CA certificate

When the pytest plugin spawns `mitmdump` for network capture,
mitmproxy uses its CA certificate to terminate HTTPS. **You are
responsible for installing the mitmproxy CA into the trust store of
the device under test** — this should only ever be done on disposable
test devices/containers, never on a developer workstation that
browses the public internet.

The plugin does **not** install the CA on your behalf and does **not**
trust the mitmproxy CA in any process other than the one being
tested.

### 3. Subprocess execution

The plugin spawns `mitmdump` via `subprocess.Popen` with a fixed
argument list. No shell interpolation. User-controlled input
(`--qa-dashboard-mitm-port`, `--qa-dashboard-host-filter`) is passed
as separate `argv` elements, not interpolated into a shell command.

### 4. HTML report XSS

The rendered HTML report includes data captured during the run. The
report generator escapes test names, error messages, and body
contents before injection. If you find an XSS path in the report,
please report it via the channel above.
