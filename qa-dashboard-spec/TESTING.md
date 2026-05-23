# Testing & Verification

How to verify each phase. Each phase's acceptance criteria are
documented in the phase file; this doc gives you the **how** for
executing them.

---

## Development without real tests: sample-data generator

`tests/fixtures/make_sample_run.py` produces a complete fake run
directory so you can iterate on the dashboard without running a
real Android emulator.

Build this in Phase 1 Task 1.10 (or Phase 2 Task 2.10 if you prefer).
It's the fastest way to iterate.

Usage:

```bash
python -m tests.fixtures.make_sample_run \
    --tests 30 --fail-rate 0.15 --steps-per-test 8 \
    --out captures/
```

Produces `captures/run_sample_<timestamp>/` with:

- A realistic manifest.json
- 30 TestRecord JSONs, mixed pass/fail/skip
- A reasonable distribution of flows, steps, screenshots
- Sample console logs
- Fake-but-valid PNG screenshots (a small solid-color PNG suffices)

The generator should be deterministic given a seed:

```bash
python -m tests.fixtures.make_sample_run --seed 42 --out captures/
```

Same seed → byte-identical output. Useful for regression testing.

---

## Phase 1 — Verification

### Setup

```bash
git clone <qa-dashboard repo>
cd qa-dashboard
pip install -e .[dev]
```

### Test 1.1 — Package imports

```bash
python -c "
import qa_dashboard
print(qa_dashboard.__version__)
from qa_dashboard.pytest_plugin import pytest_addoption
print('plugin importable')
"
```

### Test 1.2 — Plugin registers

```bash
pytest --help | grep -A 2 "qa-dashboard"
# Should show all --qa-dashboard-* options
```

### Test 1.3 — No-test invocation

```bash
mkdir /tmp/qa_test_empty && cd /tmp/qa_test_empty
pytest .  # no tests collected
ls captures/
# A run_<timestamp> directory should exist with an empty manifest.tests
```

### Test 1.4 — Minimal test, no step fixture

```bash
cat > /tmp/qa_test_empty/test_a.py <<'PY'
def test_passes(): assert True
def test_fails():  assert False, "boom"
PY
pytest test_a.py
```

Verify:

```bash
python <<'PY'
import json
from pathlib import Path
run_dir = sorted(Path("captures").glob("run_*"))[-1]
m = json.loads((run_dir / "manifest.json").read_text())
assert m["summary"]["total"] == 2
assert m["summary"]["passed"] == 1
assert m["summary"]["failed"] == 1
print("OK")
PY
```

### Test 1.5 — Step fixture works

```bash
cat > /tmp/qa_test_empty/test_b.py <<'PY'
def test_with_steps(step):
    with step("first"): pass
    with step("second"):
        step.screenshot(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100, "second-screenshot")
    with step("third that fails"):
        raise AssertionError("intentional")
PY
pytest test_b.py
```

Verify:

```bash
python <<'PY'
import json
from pathlib import Path
run_dir = sorted(Path("captures").glob("run_*"))[-1]
t = json.loads((run_dir / "tests" / "t001_test_with_steps.json").read_text())
assert t["status"] == "fail"
assert len(t["steps"]) == 3
assert t["steps"][0]["status"] == "pass"
assert t["steps"][1]["status"] == "pass"
assert t["steps"][2]["status"] == "fail"
assert t["steps"][2]["error"]["message"] == "intentional"
assert len(t["screenshots"]) == 1
shots = run_dir / "assets" / "screenshots"
assert (shots / t["screenshots"][0]["filename"]).exists()
print("OK")
PY
```

### Test 1.6 — Mitmproxy capture

Requires a real mitmproxy setup. Optional if testing on a machine
without one — set `--qa-dashboard-mitm-skip` to skip this test.

```bash
# Configure device proxy → 127.0.0.1:8080
# Then run a test that makes HTTP calls
pytest test_that_makes_http_calls.py
```

Verify the relevant TestRecord JSON has non-empty `flows` array and
each flow has a valid `step_id` (int or null).

### Test 1.7 — Plugin doesn't break a test on its own errors

Force a plugin internal failure:

```bash
# Set output directory to a read-only path
QA_DASHBOARD_DIR=/dev/null/cannot_write pytest test_a.py
```

Tests should still run and report pass/fail to stdout normally. The
plugin's failure should be a warning, not a hard crash.

### Acceptance for Phase 1

All of the above pass, plus the explicit acceptance criteria in
`PHASE_1_PLUGIN.md` section "Acceptance criteria."

---

## Phase 2 — Verification

### Setup

After Phase 2, the sample-data generator is available.

```bash
python -m tests.fixtures.make_sample_run --seed 42 --out /tmp/qa_test
ls /tmp/qa_test/run_*/
# Should include index.html now
```

### Test 2.1 — HTML opens

```bash
open /tmp/qa_test/run_*/index.html
```

In the browser:

- Page loads without console errors (open DevTools, check Console)
- Header shows run id, status, timestamp
- Metrics bar shows 6 cards with correct numbers
- Test list table populates with 30 rows
- Failed tests at top, sorted before passed
- Filter input narrows the table on type
- Status dropdown filters correctly
- Sort dropdown re-sorts correctly

### Test 2.2 — Test view navigation

- Click a passed test row → test view opens, status pill green
- URL hash updates to `#<test_id>`
- "← All tests" link returns to suite view
- Browser back button returns to suite view
- Clicking a failed test → red status, error block visible
- Tab switching works on all 6 tabs
- Step list filter works
- Network filter (text + dropdowns) works
- Network row expand/collapse works
- Screenshots tab grid renders
- Console logs tab renders

### Test 2.3 — Deep linking

Navigate directly to `index.html#t005_test_xxx/network`:

- Opens test view on Network tab
- Refresh preserves state
- Share-able URL

### Test 2.4 — Offline rendering

- Open DevTools → Network tab → set throttling to "Offline"
- Refresh `index.html`
- Should render fully (note: per-test JSONs need to be fetched from
  disk via `file://`, which works offline)

If `file://` fetch doesn't work in the user's target browser
(typically Chrome with strict file:// policies), the fallback is to
serve via a simple local HTTP:

```bash
python -m http.server 8000 -d /tmp/qa_test/run_xxx/
open http://localhost:8000/index.html
```

Document this in `troubleshooting.md`.

### Test 2.5 — CLI regeneration

```bash
rm /tmp/qa_test/run_*/index.html
qa-dashboard /tmp/qa_test/run_*/
# Recreates index.html
```

### Test 2.6 — Real-project integration

Apply the plugin to an actual test project, run, open the report,
walk through it with the QA team. Note any usability issues — they
become Phase 3 work.

### Acceptance for Phase 2

All Phase 2 acceptance criteria from `PHASE_2_REPORT.md`.

---

## Phase 3 — Verification

### Test 3.1 — Timeline interactivity

Hover steps, API bars, screenshot dots → tooltips appear with correct
data.
Click each → correct cross-tab navigation.

### Test 3.2 — Console filters

Click DEBUG pill → DEBUG lines hide.
Click ERROR pill → ERROR lines hide.
Default state: DEBUG hidden, others visible.

### Test 3.3 — Lightbox keyboard nav

Click a screenshot.
- ESC closes
- Left/Right arrows navigate
- Click backdrop closes
- Caption shown

### Test 3.4 — Print

`Cmd+P` or `Ctrl+P` in browser:
- Light mode forced
- Tabs hidden, panels expanded
- No filters/buttons
- Page breaks reasonable

### Test 3.5 — Keyboard accessibility

- Tab key cycles through interactive elements
- Arrow keys navigate tabs
- Enter activates rows
- Focus rings visible on every focusable element
- Run axe DevTools — zero serious violations

### Test 3.6 — Edge cases

Use the sample-data generator with flags:

```bash
make_sample_run --tests 0          # zero tests
make_sample_run --no-steps         # tests with no step fixture
make_sample_run --no-flows         # mitm disabled
make_sample_run --schema-version 2 # version mismatch
```

Each produces a report that renders gracefully with appropriate
empty/error states.

### Test 3.7 — Pillow downscaling

```bash
# Without Pillow installed, no downscaling
pytest tests/ --qa-dashboard-screenshot-max-width=1080
# Expected: error if Pillow missing; otherwise screenshots ≤1080 wide

pip install qa-dashboard[imaging]
pytest tests/ --qa-dashboard-screenshot-max-width=1080
# Screenshots downscaled
```

### Test 3.8 — Standalone per-test HTML

```bash
qa-dashboard captures/run_xxx/ --test t007_test_payment_fail
ls captures/run_xxx/standalone/t007_test_payment_fail.html
open captures/run_xxx/standalone/t007_test_payment_fail.html
```

Single file, opens with screenshots inlined as data URIs.

### Test 3.9 — Brand color

```ini
[pytest]
addopts = --qa-dashboard-brand-color=#dc2626
```

Run, open report, verify the brand color appears as active tab
underline / accents.

### Test 3.10 — Package install from PyPI

In a clean venv on a different machine:

```bash
pip install qa-dashboard
# OR: pip install --index-url https://test.pypi.org/simple/ qa-dashboard
pytest <some test>
```

Report generates without source-install access.

### Acceptance for Phase 3

All Phase 3 acceptance criteria from `PHASE_3_POLISH.md`.

---

## Continuous: regression suite

Build `tests/test_end_to_end.py` in the qa-dashboard repo:

```python
"""End-to-end smoke: fake artifacts → bundle → HTML → assertions."""

def test_generates_index(tmp_path, sample_run):
    # sample_run is a fixture that runs make_sample_run() into tmp_path
    generate_index_html(sample_run)
    html = (sample_run / "index.html").read_text()
    assert "<!DOCTYPE html>" in html
    assert "MANIFEST = " in html
    assert "<style>" in html
    assert len(html) < 2_000_000  # not absurdly large


def test_validation_rejects_bad_status(tmp_path):
    ...

def test_handles_parametrized_tests(tmp_path):
    ...

def test_handles_missing_screenshots(tmp_path):
    ...
```

Run in CI on every PR. Prevents regressions in schemas, templates,
or the generator.
