# qa-dashboard — Build Specification

A pip-installable pytest plugin that generates a suite-level HTML
dashboard from a pytest run, including test results, network captures
(via mitmproxy), screenshots, and console logs. Drop into any pytest
project; works across Appium, Selenium, Playwright, or plain
pytest with no driver.

## Documents in this folder

Read in this order:

1. **`README.md`** (this) — orientation
2. **`CLAUDE.md`** — instructions for the Claude Code agent
3. **`CONTEXT.md`** — why this exists, audience, constraints
4. **`ARCHITECTURE.md`** — system design, package layout, data flow
5. **`DATA_CONTRACTS.md`** — JSON schemas for every layer
6. **`UI_SPEC.md`** — visual + behavioural spec of the dashboard
7. **`PACKAGING.md`** — distribution as a pip package, integration into projects
8. **`PHASE_1_PLUGIN.md`** — first PR: pytest plugin + capture
9. **`PHASE_2_REPORT.md`** — second PR: suite-level HTML report
10. **`PHASE_3_POLISH.md`** — third PR: scale, edge cases, accessibility
11. **`REFERENCE_TEST_VIEW.html`** — visual reference for the per-test detail
12. **`TESTING.md`** — verification steps per phase

## At a glance

```
$ pip install qa-dashboard
$ # add `qa_dashboard` to pytest plugins (see PACKAGING.md)
$ pytest tests/

# Produces:
captures/run_20260522_123456/
  ├── index.html              ← open this
  ├── manifest.json           ← run metadata + test list
  ├── tests/
  │   ├── test_login_smoke.json
  │   ├── test_playback_flow.json
  │   └── ...
  └── assets/
      ├── screenshots/
      │   ├── test_login_smoke__step_4_001.png
      │   └── ...
      └── logos/ (optional)
```

One `index.html` shows the whole pytest run. Click any test to see
its step-by-step details, network flows, screenshots, console logs.

## Distribution path

`qa-dashboard` is published to PyPI. Any pytest project adopts it with:

```toml
# pyproject.toml
[project.optional-dependencies]
test = ["pytest", "qa-dashboard>=0.1"]
```

```ini
# pytest.ini  (or pyproject.toml [tool.pytest.ini_options])
[pytest]
addopts = -p qa_dashboard
```

That's the whole integration. Existing tests work unchanged; tests that
want step tracking opt in by using the `step` fixture.

## Scope — what this is

- A pytest plugin that hooks into the test lifecycle
- A capture layer that bridges mitmproxy + pytest + screenshot capture
- A static HTML+JSON+assets generator
- A CLI to regenerate reports from saved JSON

## Scope — what this is NOT

- Not a service. No backend, no database, no auth, no API.
- Not a test orchestrator. pytest does that.
- Not a cross-run history dashboard. Each run is one self-contained
  output directory; comparing across runs is a future project.
- Not a mitmproxy replacement. mitmproxy is required and out of scope
  to redesign.
- Not Allure-compatible at the file level. We can import Allure
  results in a future phase but it's not Phase 1–3.

## Why "qa-dashboard" and not something cleverer

Boring name on purpose. The package name should answer "what is it"
in one second to a stranger reading `requirements.txt`. Save
creativity for the code.
