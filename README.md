# qa-dashboard

[![PyPI](https://img.shields.io/pypi/v/qa-dashboard.svg)](https://pypi.org/project/qa-dashboard/)
[![Python](https://img.shields.io/pypi/pyversions/qa-dashboard.svg)](https://pypi.org/project/qa-dashboard/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/your-org/qa-dashboard/ci.yml?branch=main&label=CI)](https://github.com/your-org/qa-dashboard/actions/workflows/ci.yml)

A pip-installable pytest plugin that generates a suite-level HTML
dashboard from a pytest run — including test results, network captures,
screenshots, console logs, and multi-format export
(PDF, CSV, JSON, XLSX, DOCX, ZIP).

**Unified network capture (v0.7.0+).** One `flows[]` schema, four
sources:
- **mitmproxy** for pytest (Appium / native apps / anywhere)
- **Native request/response listeners** for Playwright JS/TS
- **Selenium 4 BiDi (CDP fallback)** for Python Selenium tests
- **HAR ingest** for everything else (BrowserMob, k6, JMeter,
  browser DevTools exports, Playwright `recordHar`)

Also ingests **JUnit XML** output, so Java (Maven Surefire / TestNG /
JUnit 5) and JavaScript (Jest / Playwright JS / Mocha) projects can
feed into the same dashboard.

## Quickstart — Python / pytest

```bash
pip install qa-dashboard
python -m pytest --qa-dashboard-mitm-skip
open captures/run_*/index.html
```

No `conftest.py` changes needed. The plugin auto-registers.

## Quickstart — Java / JavaScript via JUnit XML

```bash
pip install qa-dashboard
# After your normal `mvn test` (Surefire) or `gradle test` run:
qa-dashboard ingest target/surefire-reports/ \
    --screenshots-dir target/screenshots/
open captures/run_*/index.html
```

## Quickstart — HAR file (any source)

```bash
pip install qa-dashboard
# Drop in a HAR exported from browser DevTools, Playwright recordHar,
# BrowserMob, mitmproxy hardump, k6, JMeter, Postman, etc.
qa-dashboard ingest path/to/trace.har
open captures/run_*/index.html
```

Format auto-detects from `.har` / `.xml` extensions, or override with
`--format har` / `--format junit-xml`.

## Pytest options

| Option | Default | Effect |
|---|---|---|
| `--qa-dashboard-dir` | `captures` | Where to write run directories |
| `--qa-dashboard-mitm-port` | `8080` | Port for mitmdump |
| `--qa-dashboard-mitm-skip` | off | Run without mitmproxy |
| `--qa-dashboard-host-filter` | (empty) | Only capture flows matching host |
| `--qa-dashboard-screenshot-on-fail` | `true` | Auto-screenshot on failure |
| `--qa-dashboard-no-report` | off | Skip HTML generation |
| `--qa-dashboard-pretty` | `true` | Pretty-print JSON |
| `--qa-dashboard-brand-color` | (none) | Brand accent color (e.g. `#1d4ed8`) |
| `--qa-dashboard-screenshot-max-width` | (none) | Downscale screenshots (requires Pillow) |

Environment variables shadow CLI options
(`QA_DASHBOARD_DIR`, `QA_DASHBOARD_MITM_PORT`,
`QA_DASHBOARD_MITM_SKIP`, `QA_DASHBOARD_HOST_FILTER`,
`QA_DASHBOARD_SCREENSHOT_ON_FAIL`, `QA_DASHBOARD_NO_REPORT`,
`QA_DASHBOARD_PRETTY`, `QA_DASHBOARD_SCREENSHOT_MAX_WIDTH`,
`QA_DASHBOARD_BRAND_COLOR`).

### Setting options once (no per-run flags)

You don't need to pass these flags on every `pytest` command. Pick
whichever fits your project:

**1. `pyproject.toml` (recommended for pytest projects)**

```toml
[tool.pytest.ini_options]
addopts = "--qa-dashboard-dir=captures --qa-dashboard-brand-color=#1d4ed8"
```

**2. `pytest.ini` / `setup.cfg`** — same idea, `addopts = ...` under
`[pytest]` / `[tool:pytest]`.

**3. Environment variables** — commit a `.env` or set them in CI:

```bash
export QA_DASHBOARD_DIR=captures
export QA_DASHBOARD_SCREENSHOT_ON_FAIL=true
export QA_DASHBOARD_BRAND_COLOR=#1d4ed8
```

Precedence: **CLI flag > environment variable > built-in default.**

## Using the `step` fixture (optional but recommended)

```python
def test_login(driver, step):
    with step("Launch app"):
        driver.launch_app()
        step.screenshot(driver.get_screenshot_as_png(), label="splash")

    with step("Tap sign in") as s:
        s.substep("Locate button", lambda: driver.find(...))
        s.substep("Tap", lambda: driver.tap())

    with step("Verify home renders"):
        assert driver.find_element(By.ID, "home").is_displayed()
```

`step` is auto-injected — no imports needed.

## Auto-screenshot on failure (zero code required)

In v0.3.0+ the plugin detects `driver` / `page` fixtures in your tests
and captures a PNG automatically when a test fails. No callback to
register, no `conftest.py` changes.

## Multi-format export

### From the browser

The HTML report has a **⇩ Download ▾** menu in the header:
- Save as PDF (via browser print)
- Test summary (CSV)
- Full report (JSON)
- Failed tests only (CSV)

### From the command line

```bash
qa-dashboard <run-dir> --export csv
qa-dashboard <run-dir> --export json
qa-dashboard <run-dir> --export zip    # whole run, shareable
qa-dashboard <run-dir> --export xlsx   # 4-sheet workbook (requires openpyxl)
qa-dashboard <run-dir> --export docx   # Word report with embedded screenshots (requires python-docx)
```

Install with extras:

```bash
pip install qa-dashboard[xlsx]   # adds openpyxl
pip install qa-dashboard[docx]   # adds python-docx
pip install qa-dashboard[all]    # everything (Pillow + openpyxl + python-docx)
```

## Network capture support matrix

| Source | Mechanism | HTTPS / cert install? | Notes |
|---|---|---|---|
| pytest + Appium / native apps | mitmproxy auto-spawn | yes — manual | Default for pytest; works against any client that honours `HTTP(S)_PROXY` |
| pytest + Selenium 4 (Chrome/Edge) | BiDi/CDP via `bidi_network_capture` | no | See [Selenium 4 BiDi capture](#selenium-4-bidi-network-capture-python) |
| Playwright JS/TS | Native `context.on('request'/'response')` | no | Opt-in via `qa-dashboard-fixtures.js` |
| WebdriverIO | (planned) — use HAR ingest in the meantime | — | |
| Anything else | HAR ingest (`qa-dashboard ingest *.har`) | no | DevTools, BrowserMob, k6, JMeter, Postman, Playwright `recordHar` |

## Selenium 4 BiDi network capture (Python)

Use a Selenium 4 WebDriver in a pytest test, get full request/response
data in the dashboard without setting up mitmproxy or installing a CA
cert. Works automatically against Chromium-based drivers; Firefox
support depends on your Selenium version's BiDi network module.

```python
# conftest.py
import pytest
from selenium import webdriver
from qa_dashboard.integrations.selenium import bidi_network_capture

@pytest.fixture
def driver():
    d = webdriver.Chrome()
    with bidi_network_capture(d):
        yield d
    d.quit()
```

The context manager finds the active qa-dashboard run, subscribes to
network events for the lifetime of the driver, and writes captured
flows into the same `_flows/<test_id>.jsonl` layout the rest of the
plugin uses.

For browsers/drivers where automatic capture isn't available, push
flows directly into the unified sink:

```python
from qa_dashboard.integrations.selenium import FlowSink

sink = FlowSink()  # auto-discovers run dir + active test_id
sink.record(
    method="GET",
    url="https://api.example.com/users",
    status_code=200,
    response_headers={"content-type": "application/json"},
    response_body=b'{"ok": true}',
    duration_ms=42,
)
```

## Playwright TypeScript / JavaScript — native reporter (v0.7.0)

For richer step-level data than JUnit XML can carry, drop the bundled
Playwright reporter into your project. One command:

```bash
cd /your/playwright-ts-project
qa-dashboard scaffold playwright
```

That writes `qa-dashboard-reporter.js` to the project root and prints
the `playwright.config.ts` snippet you need:

```ts
import { defineConfig } from '@playwright/test';

export default defineConfig({
  reporter: [
    ['list'],
    ['./qa-dashboard-reporter.js', { outputDir: 'captures' }],
  ],
  use: {
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
});
```

Then your normal workflow:

```bash
npx playwright test
qa-dashboard captures/run_*       # generates the HTML
open captures/run_*/index.html
```

What you get vs. the JUnit XML path:

| Feature | `qa-dashboard ingest` (JUnit) | Native reporter (v0.7.0) |
|---|---|---|
| Test results, durations, errors | ✅ | ✅ |
| Auto-screenshot on failure | ✅ (with `--screenshots-dir`) | ✅ (from Playwright attachments) |
| **Step / sub-step breakdown** | ❌ | ✅ via `test.step()` |
| **Sub-step timings** | ❌ | ✅ |
| Console logs with timestamps + levels | ⚠️ heuristic | ✅ from `stdout`/`stderr` |
| Per-step screenshot grouping | ❌ | ✅ |
| Nested step support | ❌ | ✅ |
| **Network capture (request + response bodies)** | ❌ | ✅ via opt-in fixtures (below) |

### Native network capture (opt-in)

`qa-dashboard scaffold playwright` now drops two files into your
project: `qa-dashboard-reporter.js` (the reporter) and
`qa-dashboard-fixtures.js` (an extended `test` fixture that subscribes
to BrowserContext request/response events).

Switch your test imports to pick up automatic capture:

```ts
// Before:
// import { test, expect } from '@playwright/test';
// After:
const { test, expect } = require('./qa-dashboard-fixtures');
```

That's it — every test now records its full network trace into the
unified `flows[]` schema and you'll see a populated **Network** tab
in the dashboard. Bodies are capped at 100 KB (configurable via
`test.use({ qaDashboard: { maxBodyBytes: 524288 } })`).

Tests using Playwright's native step syntax produce full breakdowns:

```ts
test('login flow', async ({ page }) => {
  await test.step('Open login page', async () => {
    await page.goto('/login');
  });
  await test.step('Enter credentials', async () => {
    await page.fill('#email', 'x@y.com');
    await page.fill('#password', 'pw');
  });
  await test.step('Submit and verify', async () => {
    await page.click('#submit');
    await expect(page).toHaveURL('/home');
  });
});
```

…shows up as three explicit steps in the dashboard with individual
timings, nested actions as sub-steps, and any screenshots attached to
the step where they were taken.

## WebdriverIO — native reporter (v0.7.0)

For WDIO + Mocha / Jasmine / Cucumber projects, drop the bundled
reporter into your project. One command:

```bash
cd /your/wdio-project
qa-dashboard scaffold webdriverio
```

That writes `qa-dashboard-wdio-reporter.js` to the project root and
prints the `wdio.conf.js` snippet you need:

```js
const QaDashboardReporter = require('./qa-dashboard-wdio-reporter');

exports.config = {
  reporters: [
    'spec',
    [QaDashboardReporter, { outputDir: 'captures' }],
  ],
  // ...
};
```

Then your normal workflow:

```bash
npx wdio run wdio.conf.js
qa-dashboard captures/run_*
open captures/run_*/index.html
```

What you get automatically:

- Per-test pass/fail/skip with durations
- Suite hierarchy in test nodeids (`Suite > Sub-suite > test name`)
- Auto-capture of `browser.takeScreenshot()` results
- Auto-capture of `browser.saveScreenshot(path)` files
- Failure error message + stack trace
- Capability info (browser, platform, Appium device) attached as `device`
- Multi-worker safe — workers converge on a single run directory via a
  lockfile in `outputDir`

## Java / JavaScript integration via `qa-dashboard ingest` (JUnit XML)

```bash
# Maven (Surefire / Failsafe)
mvn test
qa-dashboard ingest target/surefire-reports/

# Gradle
./gradlew test
qa-dashboard ingest build/test-results/test/

# Jest (with junit reporter)
npx jest --reporters=jest-junit
qa-dashboard ingest junit.xml

# Attach screenshots saved by your tests:
qa-dashboard ingest target/surefire-reports/ --screenshots-dir target/screenshots/
```

The ingestor matches screenshots to tests by filename — if a PNG's
filename contains the test method or class name, it's auto-attached.

## What's automatic vs. what needs your code

**Automatic with zero project code:**
- Test results, durations, tags, parametrize parameters
- Console logs (stdlib `logging`)
- Environment info (Python, OS, pytest, git branch/commit)
- Network capture (when mitmproxy isn't skipped)
- Failure screenshots (driver/page auto-detected)
- HTML report + download buttons

**Needs you to add code:**
- Named per-step breakdowns (`with step("…"):`) — user intent
- Custom screenshot labels (`step.screenshot(png, label="…")`)
- Device/app metadata (`qa_dashboard_test.set_device(…)`)

## Security & redaction

qa-dashboard captures HTTP traffic and writes it to disk. The
following headers are redacted to `***` by default before being
persisted:

`authorization`, `cookie`, `set-cookie`, `x-api-key`, `x-auth-token`,
`proxy-authorization`

Extend or replace the list:

```bash
pytest --qa-dashboard-redact "authorization,x-internal-token,password"
# or
export QA_DASHBOARD_REDACT="authorization,x-internal-token,password"
```

Matches are case-insensitive substrings against header names **and**
top-level JSON body keys. See [SECURITY.md](SECURITY.md) for the full
threat model and how to report vulnerabilities.

## Diagnose a run

```bash
qa-dashboard doctor captures/run_*
```

Validates the manifest and per-test JSON records, cross-references
flows/screenshots/steps, and exits non-zero on any structural issue.
Useful in CI right after a test run, before publishing the report.

## Stability policy

qa-dashboard follows SemVer. Within `0.x`:

- **The on-disk data contract (`schema_version: 1`)** is stable. We
  will not break `manifest.json` / `tests/*.json` consumers within a
  major schema version.
- **CLI flags and pytest options** are stable across minor releases on
  a best-effort basis. Renames get one minor of deprecation warning.
- **The Python public API** is the names listed in each module's
  `__all__`. Private names start with `_`.
- **JS reporter options** are stable across minor releases.

See [CHANGELOG.md](CHANGELOG.md) for the full release history.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). TL;DR: `pip install -e
".[dev,all,mitm]"`, then `ruff check .`, `mypy src/qa_dashboard`,
`pytest --cov=qa_dashboard --cov-fail-under=80`.

## License

MIT — see [LICENSE](LICENSE).
