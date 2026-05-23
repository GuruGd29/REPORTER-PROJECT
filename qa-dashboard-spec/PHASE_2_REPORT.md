# Phase 2 — HTML report generation

**Goal:** Take Phase 1's JSON artifacts and produce a working
`index.html` that renders both the suite view and per-test detail view.

**Prerequisite:** Phase 1 verified. JSON artifacts produced cleanly.

**Estimated size:** 1 PR. ~1500 lines: HTML template, CSS, JS, generator
code, CLI.

**Visual contract:** `REFERENCE_TEST_VIEW.html` in this folder for the
per-test view. The suite view is new — build it against `UI_SPEC.md`.

---

## Task checklist

### Task 2.1 — Templates layout

`src/qa_dashboard/report/templates/`:

```
templates/
├── index.html        # Outer page; loads manifest, swaps suite/test views
├── styles.css        # All styling, light + dark mode
└── runtime.js        # All JS: routing, suite view, test view, lightbox
```

The outer `index.html` is the only HTML file. The JS handles both views.

### Task 2.2 — Generator

`src/qa_dashboard/report/generator.py`:

```python
def generate_index_html(run_dir: Path) -> None:
    """Read manifest.json, render index.html, write it next to manifest."""

    manifest = json.loads((run_dir / "manifest.json").read_text())
    template = (TEMPLATES_DIR / "index.html").read_text()
    css = (TEMPLATES_DIR / "styles.css").read_text()
    js = (TEMPLATES_DIR / "runtime.js").read_text()

    html = Template(template).substitute(
        title=f"Run {manifest['run_id']} — {manifest['status']}",
        styles=css,
        runtime_js=js,
        manifest_json=json.dumps(manifest, ensure_ascii=False),
    )
    (run_dir / "index.html").write_text(html, encoding="utf-8")
```

Only the manifest is embedded. Per-test JSONs are fetched on demand.

### Task 2.3 — Outer template

`templates/index.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>$title</title>
  <style>$styles</style>
</head>
<body>
  <header id="header"></header>
  <div id="metrics"></div>
  <main id="view"></main>
  <div id="lightbox" hidden></div>
  <script>
    const MANIFEST = $manifest_json;
  </script>
  <script>$runtime_js</script>
</body>
</html>
```

Two `<script>` blocks: one for the data const, one for the runtime.
This makes the manifest line visible/diffable in the source and keeps
the runtime JS reusable.

### Task 2.4 — Runtime JS structure

`templates/runtime.js`:

```javascript
// ============================================================
//  Routing
// ============================================================
function parseHash() {
  // #t001/network/flow_17 → { testId: "t001", tab: "network", focus: "flow_17" }
  const h = window.location.hash.slice(1);
  if (!h) return { view: "suite" };
  const [testId, tab, focus] = h.split("/");
  return { view: "test", testId, tab: tab || "steps", focus };
}

function applyRoute() {
  const route = parseHash();
  if (route.view === "suite") renderSuiteView();
  else renderTestView(route.testId, route.tab, route.focus);
}

window.addEventListener("hashchange", applyRoute);
window.addEventListener("DOMContentLoaded", () => {
  renderHeader();
  renderMetrics();
  applyRoute();
});

// ============================================================
//  Suite view
// ============================================================
function renderSuiteView() {
  // From MANIFEST.tests: build the test list table
  // Filter + sort controls update the table
}

// ============================================================
//  Test view
// ============================================================
let testRecordCache = {};
async function renderTestView(testId, tab, focus) {
  let record = testRecordCache[testId];
  if (!record) {
    const resp = await fetch(`tests/${testId}.json`);
    record = await resp.json();
    testRecordCache[testId] = record;
  }
  renderTestHeader(record);
  renderTab(tab, record, focus);
}

// ============================================================
//  Lightbox
// ============================================================
// ...
```

Keep this readable. Don't minify. The whole runtime should fit in ~500
lines of vanilla JS.

### Task 2.5 — CSS

`templates/styles.css`:

Reuse most of `REFERENCE_TEST_VIEW.html`'s CSS verbatim. The new
additions are:

- The suite view: test list table styling
- The toolbar above the test list (filter, status dropdown, sort)
- The "← All tests" link
- The route-transition state (no animation, just instant swap)

### Task 2.6 — Suite view in JS

The renderer reads `MANIFEST.tests`, applies filter/sort, and emits
the test list table. On row click:

```javascript
row.addEventListener("click", () => {
  window.location.hash = test.test_id;
  // applyRoute fires automatically
});
```

### Task 2.7 — Test view in JS

When `renderTestView` is called, it:

1. Fetches `tests/<test_id>.json` (cached after first fetch)
2. Renders the test header (status badge, name, nodeid, duration)
3. Renders the tab bar
4. Renders the active tab's content

Tabs are the six from `REFERENCE_TEST_VIEW.html`. The implementation
of each tab is essentially copy-paste from the reference, with two
differences:

1. Data source is `record.steps`, `record.flows`, etc. (instead of
   the const-based sample data)
2. URL hash updates on tab switch and on row expansion (so deep
   links work)

### Task 2.8 — CLI

`src/qa_dashboard/cli.py`:

```python
def main(argv=None):
    parser = argparse.ArgumentParser("qa-dashboard")
    parser.add_argument("run_dir", help="Path to a qa-dashboard run directory")
    parser.add_argument("--force", action="store_true",
                        help="Regenerate even if index.html exists")
    args = parser.parse_args(argv)
    run_dir = Path(args.run_dir)
    if not (run_dir / "manifest.json").exists():
        sys.exit(f"No manifest.json in {run_dir}")
    generate_index_html(run_dir)
    print(f"Generated {run_dir / 'index.html'}")
```

Wire into `pyproject.toml`:

```toml
[project.scripts]
qa-dashboard = "qa_dashboard.cli:main"
```

After `pip install`, users can run:

```bash
qa-dashboard captures/run_20260522_*/
```

### Task 2.9 — Wire generator into plugin

In `pytest_plugin.py`, at `pytest_sessionfinish`:

```python
def pytest_sessionfinish(session, exitstatus):
    plugin = session.config.stash[_state_key]
    plugin.manifest.finalize(...)
    if plugin.mitm:
        plugin.mitm.stop()
    if not plugin.no_report:
        try:
            generate_index_html(plugin.run_dir)
            print(f"\nqa-dashboard: report at {plugin.run_dir / 'index.html'}")
        except Exception:
            logging.exception("qa-dashboard: failed to generate index.html")
            print(f"\nqa-dashboard: HTML generation failed; "
                  f"JSON artifacts are in {plugin.run_dir}", file=sys.stderr)
```

### Task 2.10 — Sample-data generator (for development without real tests)

`tests/fixtures/make_sample_run.py` in the qa-dashboard repo:

```python
"""Generate a fake run directory for dashboard development."""

def main(out_root: Path = Path("captures"), num_tests: int = 30, fail_rate: float = 0.15):
    ...
```

Produces a complete run directory with 30 tests, mixed pass/fail/skip,
flows, screenshots, console logs. Used to iterate on the dashboard
without running real tests.

Make this a `pytest` command:

```bash
python -m tests.fixtures.make_sample_run --tests 50 --fail-rate 0.2
qa-dashboard captures/run_sample_*/
open captures/run_sample_*/index.html
```

---

## Acceptance criteria

1. `pytest tests/` (in a project using the plugin) produces both
   the JSON artifacts AND `index.html`
2. Opening `index.html` shows the suite view: test list, summary
   metrics, filter/sort controls
3. Clicking a test row opens the test view with the test's name in
   the URL hash
4. The test view's tabs work as in `REFERENCE_TEST_VIEW.html`
5. Tab switches update the URL hash
6. Sharing `index.html#t002_test_foo/network` opens directly on that
   test's Network tab
7. The "← All tests" link returns to suite view
8. Browser back/forward navigates between suite and test views
9. With network disabled (test offline behaviour), the report still
   renders (no CDN dependencies)
10. The page handles tests that are skipped, failed, parametrized,
    and zero-step gracefully
11. `qa-dashboard captures/run_xxx/` regenerates the HTML from JSON
12. Sample run generator works: `python -m tests.fixtures.make_sample_run`
    produces a usable demo report

---

## File size targets

- `index.html` (with embedded manifest for 200 tests): < 500 KB
- Single TestRecord JSON (typical): 50–500 KB
- Single TestRecord JSON (worst case, lots of flow bodies): 2 MB
- Total `assets/` for 200 tests with 10 screenshots each: 200–1000 MB
  (screenshots dominate; that's expected)

If `index.html` grows past 1 MB, examine what's bloating the manifest
and trim it. The manifest summary per test should be small (~300 bytes
each). For 200 tests, 60 KB of manifest is reasonable.

---

## OUT of Phase 2

- Timeline interactivity (hover tooltips, click-to-jump) → Phase 3
- Console log filter UI → Phase 3
- Print stylesheet polish → Phase 3
- Screenshot lightbox keyboard nav → Phase 3 (basic click-to-open in)
- Pillow-based screenshot downscaling → Phase 3
- Per-test standalone rendering via CLI (`qa-dashboard --test t001`) → Phase 3
- Cross-run history → never (separate project)

---

## Questions to ask before starting Phase 2

1. Should `index.html` be self-contained (CSS + JS inlined) or should
   it reference `assets/styles.css` and `assets/runtime.js`? Inlined
   is simpler; external is better for caching across runs. Default:
   inlined.
2. Should the suite view default to showing failed tests only, or all?
   Default: all but sorted failed-first.
3. Color theme — should this support a custom brand color via a
   CSS variable override, or stick to the default palette? Default:
   default only in Phase 2; brand customization in Phase 3.
4. What's the minimum browser? Chrome 100+ / Firefox 100+ / Safari 15+?
