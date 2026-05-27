# qa-dashboard

A pip-installable pytest plugin that generates a suite-level HTML
dashboard from a pytest run — including test results, network captures
(via mitmproxy), screenshots, console logs, and multi-format export
(PDF, CSV, JSON, XLSX, DOCX, ZIP).

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
(`QA_DASHBOARD_DIR`, `QA_DASHBOARD_MITM_PORT`, ...).

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

## Playwright TypeScript / JavaScript — native reporter (v0.5.0)

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

| Feature | `qa-dashboard ingest` (JUnit) | Native reporter (v0.5.0) |
|---|---|---|
| Test results, durations, errors | ✅ | ✅ |
| Auto-screenshot on failure | ✅ (with `--screenshots-dir`) | ✅ (from Playwright attachments) |
| **Step / sub-step breakdown** | ❌ | ✅ via `test.step()` |
| **Sub-step timings** | ❌ | ✅ |
| Console logs with timestamps + levels | ⚠️ heuristic | ✅ from `stdout`/`stderr` |
| Per-step screenshot grouping | ❌ | ✅ |
| Nested step support | ❌ | ✅ |

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

## WebdriverIO — native reporter (v0.6.0)

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

See `qa-dashboard-spec/` for the full specification.
