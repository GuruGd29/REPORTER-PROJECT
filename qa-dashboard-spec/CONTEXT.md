# Context

## Why this project exists

A QA team runs automated test suites (pytest + Appium / Selenium /
Playwright / plain pytest, with mitmproxy capturing all HTTP/HTTPS
traffic during each test). The team has working capture infrastructure
(`mitm_addon.py`, `mitm_live.py`, an existing `mitm_report.py`) but the
existing reports are **per-test** — one HTML file per test function.

A typical pytest invocation runs 50–500 tests. That produces 50–500
HTML files. Engineers want to:

1. Open one report and see all tests
2. See which ones failed at a glance
3. Click any failed test to drill into its steps, network, screenshots
4. Forward the report to a backend engineer or PM

The current per-test architecture cannot do this. Engineers triage
failures by `ls captures/`, open files one at a time, and lose context
constantly.

`qa-dashboard` replaces the per-test report with a suite-level report.

It is also a **portable, pip-installable package** — usable on the
current Android Hotstar project and any future pytest project the team
adopts. The team has multiple internal projects and wants one shared
dashboard rather than copy-pasted forks per repo.

## Existing infrastructure

These files already exist in the original project. The plugin must
work alongside them without modification, except for the targeted
changes called out in Phase 1.

| File | Role | Plugin's relationship |
|---|---|---|
| `mitm_addon.py` | mitmproxy addon capturing flows | Plugin reads its JSON output; minor extension for `step_id` tagging |
| `mitm_live.py` | SSE live dashboard | Untouched. Different use case. |
| `mitm_report.py` | Per-test static report | Deprecated by this plugin. Keep working through Phase 2 for parity testing; remove or rename in Phase 3 if user approves. |
| `conftest.py` | pytest fixtures incl. `mitm_proxy` | Plugin coexists. Users keep their existing `mitm_proxy` fixture; plugin hooks pytest lifecycle separately. |

In new projects adopting `qa-dashboard`, the user starts from scratch
with `pip install qa-dashboard` and follows `PACKAGING.md`. They don't
need a pre-existing `mitm_addon.py` — the package ships its own.

## Audience

Three personas, optimised in this order:

### 1. QA engineer triaging a failed CI run
- Opens the report URL from a CI pipeline notification
- Wants to know: how many tests failed, which ones, why
- Then drills into one failed test to see step, network, screenshot
- Spends 10–30 minutes per session
- Critical features: failed-tests-first sorting, fast test list filter,
  step/network/screenshot correlation per test

### 2. Backend engineer asked by QA to look at an API issue
- Opens the link QA sent
- Often shares a screenshot or paragraph from QA, then needs to find
  the same content in the report
- Wants raw network: request, response, headers, latency
- Spends 5–10 minutes per session
- Critical features: per-test network tab, body viewer, easy "copy URL"

### 3. Project manager / release manager checking suite health
- Opens to see pass rate, regression count
- Doesn't drill into individual tests
- Spends < 1 minute per session
- Critical features: suite-level summary at the top of `index.html`

When making UX tradeoffs, optimise for persona 1.

## Hard constraints (cannot be violated)

### 1. The report is a static directory of files

```
captures/run_<timestamp>/
  ├── index.html
  ├── manifest.json
  ├── tests/*.json
  └── assets/screenshots/*.png
```

No server, no API endpoints, no database. The directory can be zipped
and emailed. Opened with `file://` and works the same as served over
HTTP.

### 2. Screenshots live in `assets/`, not inlined

This is the deliberate departure from the per-test mockup. At suite
scale (200 tests × 30 screenshots × 200KB each = 1.2 GB of images),
inlining as base64 makes the HTML unusable. Browsers refuse to render
files over ~100 MB.

Consequence: to share a report, you share the **directory**, not a
single file. Zip it. Upload to S3. Whatever. The HTML alone is
useless because the `<img src="assets/screenshots/...">` references
break.

Per-test JSON files are individually portable — if QA wants to share
just one failed test, they can send `tests/test_login_smoke.json` and
the user can render it standalone via the CLI.

### 3. No external runtime dependencies in the HTML

The HTML uses only:
- Inlined CSS
- Inlined vanilla JS
- Relative-path references to images in `assets/`
- System fonts (no `@font-face` from CDN)

Reason: corporate networks, offline viewing, archival longevity.

### 4. pip-installable, public-API stable

The package is published to PyPI. Users adopt with `pip install
qa-dashboard`. The public API — fixture names, plugin name, output
directory shape — is stable across minor versions per semver. Breaking
changes require a major version bump.

This is what makes "usable for older and newer projects" real. A
project written today against `qa-dashboard==0.2` should still work
when `qa-dashboard==0.7` is current, as long as 0.7 is still 0.x.

### 5. mitmproxy is required, but failure is non-fatal

The plugin assumes mitmproxy is available and the project's tests
route through it. But if mitmproxy fails to start, or no flows are
captured for a particular test, the report still renders — just with
an empty Network tab for that test.

The plugin must not crash the test suite if its own capture pipeline
hits an error. The dashboard is observability, not the system under
test.

## Soft constraints (preferences, not hard rules)

- Dependency-light. stdlib-only for the core. Pillow allowed for
  screenshot downscaling, Jinja2 NOT allowed (stdlib `string.Template`
  is enough).
- No JS frameworks. Vanilla JS in the HTML.
- File output should be deterministic — same inputs produce the same
  HTML bytes. (For diffing reports, content-hashing, archival.)
- Python 3.10+. Don't worry about 3.8/3.9.

## Definition of done (whole project)

A QA engineer can:

1. `pip install qa-dashboard` into a fresh project
2. Add `-p qa_dashboard` to their `pytest.ini`
3. Run `pytest` (no test code changes needed for basic usage)
4. Get `captures/run_<timestamp>/index.html`
5. Open it, see all tests with pass/fail status
6. Click any test → see its steps, network, screenshots, logs
7. Filter the test list by status, name, or duration
8. Forward the `captures/run_<timestamp>/` directory to a colleague,
   who opens `index.html` and sees the same thing

And, once a project opts in further by using the `step` fixture in
test functions:

9. Test detail view shows step-level granularity, sub-steps, per-step
   screenshots, and per-step network flow scoping

## What "across older and newer projects" actually means

Concretely:

- The team's current Hotstar Android project (Appium-based) installs
  `qa-dashboard`, replaces `mitm_report.py` calls with the plugin,
  keeps everything else. Phase 3 deliverable.
- A future Hotstar web project (Selenium / Playwright) installs the
  same `qa-dashboard`, configures it for the web driver, and gets
  the same report shape with web-specific screenshots. No code changes
  to `qa-dashboard` itself required, assuming the user provides
  screenshots via the `step` fixture's `attach_screenshot()` API.
- A future API testing project (pytest + requests, no UI) installs
  `qa-dashboard`, doesn't use screenshots or steps, and still gets
  a useful report with network flows and pass/fail per test.

The framework-agnosticism is **enforced by not depending on Appium,
Selenium, or Playwright in the package**. Users bring their own
driver; the plugin only consumes generic artifacts (screenshots as
bytes, step events as strings, console logs from stdlib `logging`).
