# Changelog

All notable changes to qa-dashboard are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/) with
the stability commitments described in **Stability policy** at the bottom.

## [Unreleased]

## [0.9.0] - 2026-06-12

### Added
- `qa-dashboard publish-static <run-dir> --to <destination>` — uploads
  a run to any S3-compatible bucket or local filesystem path and
  refreshes a rolling `index.html` of recent runs at the destination
  root. The Allure-style hosting model: no backend, no database, no
  Docker. Supports AWS S3, Cloudflare R2, Backblaze B2, MinIO,
  DigitalOcean Spaces, and `file:///` for GitHub Pages workflows.
- New `[publish]` optional dependency adds `boto3` for S3 publishing.
- `qa_dashboard.publish` Python API (`Publisher`,
  `FilesystemPublisher`, `S3Publisher`, `publish_static`) for
  programmatic use.
- 21 new unit tests for the publish path (filesystem end-to-end,
  rollup merging + trimming + dedupe, S3 mocked).

### Notes
- A microservices "cloud MVP" was briefly scaffolded earlier in this
  release cycle and then **deliberately abandoned** in favour of
  static hosting. Static publishing matches how 90%+ of teams actually
  share test reports (the Allure model) and adds zero operational
  surface compared to a hosted service. If multi-tenant SaaS becomes
  a real requirement later, the cloud track can be revisited.

## [0.8.0] - 2026-06-11

### Added
- `qa-dashboard doctor <run-dir>` — health check that validates manifest,
  per-test JSON records, and cross-references between flows / screenshots /
  steps. Exits non-zero on any structural problem.
- Header and body redaction for captured network traffic. New
  `--qa-dashboard-redact` flag and `QA_DASHBOARD_REDACT` env var redact
  any matched header or JSON body key by case-insensitive substring match.
  Defaults to redacting common credential headers (`authorization`,
  `cookie`, `set-cookie`, `x-api-key`, `x-auth-token`,
  `proxy-authorization`).
- Mitm subprocess failures are now surfaced at session teardown — the
  pytest plugin tails `_flows/_addon_errors.log` and emits a warning if
  the addon hit any errors during the run.
- Lazy mitmproxy import. Mitmproxy is now an optional install:
  `pip install qa-dashboard` (core) vs `pip install qa-dashboard[mitm]`.
- Unit tests for the HAR parser, Selenium `FlowSink`, redaction, the
  doctor command, plugin helpers, and schema edge cases — 102 tests
  total (up from 33). Coverage gate set to 55% with a roadmap to
  raise as more mitmproxy-subprocess code becomes testable.
- Continuous-integration matrix on Python 3.10/3.11/3.12/3.13 across
  Ubuntu, macOS, and Windows. Adds lint (ruff), type-check (mypy on the
  public API), and PR-blocking coverage threshold.
- `examples/` directory with runnable starter projects for Playwright
  TS, pytest+Selenium 4 BiDi, and HAR ingest.
- README badges, stability policy, and security/redaction documentation.

### Changed
- Structured logging via `logging.getLogger("qa_dashboard.<area>")` in
  every module. Previously-silenced `except Exception` blocks now log at
  `WARNING` or `DEBUG` level so users can diagnose capture failures.
- `__all__` declared on every public module so `from x import *` is well
  defined.

### Fixed
- Broken README reference to `qa-dashboard-spec/` (directory did not
  exist). Spec content folded back into the README.

## [0.7.0] - 2026-05-27

### Added
- Unified network capture across frameworks. One `flows[]` schema, four
  sources:
  - mitmproxy auto-spawn (existing, for pytest + Appium/native apps).
  - Playwright JS/TS native capture via
    [`qa-dashboard-fixtures.js`](src/qa_dashboard/integrations/playwright/qa-dashboard-fixtures.js).
    Opt-in by importing `test`/`expect` from the fixtures file.
  - Selenium 4 BiDi/CDP capture via
    `qa_dashboard.integrations.selenium.bidi_network_capture`.
  - HAR 1.2 ingest: `qa-dashboard ingest <file>.har`. Format
    auto-detected by extension; `--format har` is also accepted.
- `FlowSink` for pushing flows from any custom capture source.
- Network capture support matrix in the README.

### Changed
- Playwright reporter `flows: []` hardcode replaced with attachment-based
  capture. The reporter now emits `flow_count` correctly in the manifest.
- `qa-dashboard scaffold playwright` now drops both
  `qa-dashboard-reporter.js` and `qa-dashboard-fixtures.js`.

## [0.6.0] - prior to changelog

- WebdriverIO native reporter.

## [0.5.0] - prior to changelog

- Playwright TS/JS native reporter; auto-flatten screenshots.

## [0.4.0] - prior to changelog

- Initial public release.

---

## Stability policy

qa-dashboard follows SemVer with these specific commitments:

- **The on-disk data contract (`schema_version`)** is the strongest
  guarantee. We will not break consumers of `manifest.json` or
  `tests/*.json` within a major schema version. A schema break bumps
  `schema_version` and is called out in the changelog under a
  **BREAKING** heading.
- **The CLI and pytest flags** are stable across minor versions during
  `0.x` *as a best-effort*. Renames are deprecated for one minor version
  before removal and emit a `DeprecationWarning`.
- **The Python public API** is `qa_dashboard.<module>` names listed in
  each module's `__all__`. Private names start with `_` and may change
  at any time.
- **JS reporter options** (`outputDir`, etc.) are stable across minor
  versions.

When we hit 1.0 these commitments become strict — including across
major releases of frameworks we integrate with (Playwright, Selenium,
WebdriverIO).
