# Architecture

## Package layout

```
qa-dashboard/
├── pyproject.toml
├── README.md
├── LICENSE
├── src/
│   └── qa_dashboard/
│       ├── __init__.py
│       ├── pytest_plugin.py        # pytest hooks, registered as plugin
│       ├── fixtures.py             # the `step` fixture and StepTracker
│       ├── capture/
│       │   ├── __init__.py
│       │   ├── mitm_addon.py       # shipped mitmproxy addon
│       │   ├── mitm_manager.py     # starts/stops mitmdump per session
│       │   └── step_channel.py     # side-channel file for step_id
│       ├── bundle/
│       │   ├── __init__.py
│       │   ├── builder.py          # assembles RunBundle from artifacts
│       │   ├── schemas.py          # validation logic
│       │   └── derivations.py      # derived metrics (pass rate, etc.)
│       ├── report/
│       │   ├── __init__.py
│       │   ├── generator.py        # produces index.html + per-test JSON
│       │   ├── templates/
│       │   │   ├── index.html      # suite view template
│       │   │   ├── test_view.html  # per-test detail template (currently
│       │   │   │                   #  embedded; future: standalone via CLI)
│       │   │   ├── styles.css
│       │   │   └── runtime.js
│       │   └── encoders.py         # JSON/HTML safe encoding
│       └── cli.py                  # `python -m qa_dashboard <run-dir>`
│
└── tests/
    ├── test_plugin_smoke.py
    ├── test_bundle_builder.py
    ├── test_report_generator.py
    ├── fixtures/
    │   └── make_sample_run.py      # generates fake artifacts for dev
    └── ...
```

## High-level data flow

```
┌───────────────────────────────────────────────────────────────┐
│  $ pytest tests/                                              │
│                                                               │
│  pytest_plugin.py registers itself, parses --qa-dashboard-*   │
│  options, creates a unique run_id and capture_dir.            │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │  pytest_sessionstart                                    │  │
│  │   - mkdir captures/run_<timestamp>/                     │  │
│  │   - start mitmdump subprocess (mitm_manager.py)         │  │
│  │   - write manifest.json scaffold                        │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                               │
│  for each test:                                               │
│   ┌─────────────────────────────────────────────────────────┐ │
│   │  pytest_runtest_setup                                   │ │
│   │   - allocate test_id, create per-test capture state     │ │
│   │   - point mitm_addon at this test's flow output         │ │
│   ├─────────────────────────────────────────────────────────┤ │
│   │  test function runs                                     │ │
│   │   - uses `step` fixture (optional)                      │ │
│   │   - step writes step_id to side-channel file            │ │
│   │   - mitm_addon tags every flow with current step_id     │ │
│   │   - screenshots written to assets/screenshots/          │ │
│   │   - logging captured to per-test JSONL                  │ │
│   ├─────────────────────────────────────────────────────────┤ │
│   │  pytest_runtest_teardown                                │ │
│   │   - finalize step tracker                               │ │
│   │   - capture pytest outcome (pass/fail/skip + reason)    │ │
│   │   - write tests/<test_id>.json (TestRecord)             │ │
│   │   - append test summary to manifest.json                │ │
│   └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │  pytest_sessionfinish                                   │  │
│  │   - stop mitmdump                                       │  │
│  │   - finalize manifest.json                              │  │
│  │   - generate index.html via report.generator            │  │
│  │   - print: "Report at captures/run_<timestamp>/         │  │
│  │            index.html"                                  │  │
│  └─────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────┘
```

## Output directory shape

```
captures/run_20260522_123456_abc123/        ← run_id includes random suffix
  ├── index.html                            ← suite view, open this
  ├── manifest.json                         ← run metadata + test list
  ├── tests/
  │   ├── t001_test_login_smoke.json        ← TestRecord per test
  │   ├── t002_test_playback_flow.json
  │   └── ...
  └── assets/
      ├── screenshots/
      │   ├── t001_step_4_001.png
      │   ├── t001_step_7_001.png
      │   ├── t002_step_2_001.png
      │   └── ...
      ├── styles.css                        ← optional: extracted for caching;
      │                                        Phase 2 default is inlined,
      │                                        extracted is Phase 3 polish
      └── runtime.js                        ← same as styles.css
```

The `tests/<test_id>.json` files are self-contained per test (they
include their own flows, console lines, step list). The `index.html`
loads each one on demand via `fetch()` when the user clicks into a
test, rather than embedding everything upfront.

This makes the index page small (~200 KB regardless of suite size)
and lazy-loads heavy data only when needed.

### Lazy loading approach

```javascript
// In index.html runtime.js:
async function openTest(testId) {
  const resp = await fetch(`tests/${testId}.json`);
  const testRecord = await resp.json();
  renderTestDetail(testRecord);
}
```

Yes, `fetch()` from `file://` works in all modern browsers when the
target is a sibling file in the same directory. Firefox is the
strictest — confirm in Phase 2 testing.

If `file://` fetch ever becomes a problem, the fallback is to embed
all TestRecord JSONs in `index.html` as a `<script>` block. That's
the Phase 3 escape hatch.

## test_id naming

Each test gets a stable `test_id` of the form:

```
t<seq>_<sanitized_nodeid>
```

Where:
- `<seq>` is a zero-padded 3-digit sequential number per run
- `<sanitized_nodeid>` is the pytest nodeid with `/`, `::`, `[`, `]`
  replaced by `_`, truncated to 80 chars

Examples:
```
t001_tests_Android_phase2_test_test_login_smoke
t042_tests_api_test_payment_test_refund_eligible_user_returns_200
```

This means filenames are valid on Windows and macOS, sort in run
order, and remain greppable by test name.

## Cross-process state: the step side-channel

mitmproxy runs in a subprocess. pytest runs in the parent. They cannot
share Python objects. We tag each captured flow with the current step
via a file:

```
captures/run_<timestamp>/current.txt

Format: "<test_id>\t<step_id>"   e.g.  "t001_test_login\t7"
        ""                       (between steps or between tests)
```

- `step.__enter__` writes the new value atomically (via `os.replace`)
- `step.__exit__` clears the file
- `pytest_runtest_setup` writes `"<test_id>\t0"` (test active, no step)
- `pytest_runtest_teardown` clears the file
- `mitm_addon.py` reads on every captured flow, tags
  `(test_id, step_id)` onto the entry

This is intentionally simple and debuggable. `cat current.txt` shows
you exactly where the system is right now. No IPC libraries.

## Configuration via pytest options

Users configure via command-line flags or `pytest.ini`:

```ini
[pytest]
addopts =
    -p qa_dashboard
    --qa-dashboard-dir=captures
    --qa-dashboard-mitm-port=8080
    --qa-dashboard-host-filter=hotstar
    --qa-dashboard-screenshot-on-fail=true
```

| Option | Default | Effect |
|---|---|---|
| `--qa-dashboard-dir` | `captures` | Where to write run directories |
| `--qa-dashboard-mitm-port` | `8080` | Port for mitmdump |
| `--qa-dashboard-mitm-skip` | `false` | Run without mitmproxy (network tab empty) |
| `--qa-dashboard-host-filter` | (empty) | Only capture flows whose host matches |
| `--qa-dashboard-screenshot-on-fail` | `true` | Auto-capture screenshot at failure if `step` fixture is active and `attach_screenshot` callback is set |
| `--qa-dashboard-no-report` | `false` | Skip HTML generation (JSON only) |

All readable via `request.config.getoption(...)` in fixtures.

Environment variables shadow CLI options:
- `QA_DASHBOARD_DIR`
- `QA_DASHBOARD_MITM_PORT`
- etc.

CLI > env > pytest.ini > defaults.

## What gets generated when

### During the run (incremental)

These files are written *as the run proceeds*, so a crashed pytest
still leaves a partial report:

- `current.txt` (continuously)
- `manifest.json` (initial scaffold at session start; updated per test)
- `tests/<test_id>.json` (after each test's teardown)
- `assets/screenshots/*.png` (during each test)

### At session end (final)

- `manifest.json` (final form, with end timestamp + aggregates)
- `index.html` (generated last, after all tests done)

If pytest is killed mid-run (`Ctrl+C`, OOM, etc.), the user can run
the CLI manually to generate the HTML from whatever artifacts exist:

```
python -m qa_dashboard captures/run_<timestamp>/
```

The CLI tolerates a missing or in-progress manifest and produces a
best-effort report.

## Why JSON files per test, not one big JSON?

Three reasons:

1. **Crash safety.** Each test's data is flushed to disk at its own
   teardown. A pytest crash mid-suite loses only the in-flight test.
2. **Lazy loading.** Browser fetches only the test the user clicks
   into. Faster initial page render.
3. **Standalone reuse.** A single `tests/<test_id>.json` can be
   rendered by the CLI as its own mini-report.

The cost is more files on disk. For 500 tests, that's 500 JSON files
+ a manifest + index.html + assets. Filesystem handles this trivially.

## The pytest plugin entry point

`pyproject.toml`:

```toml
[project.entry-points.pytest11]
qa_dashboard = "qa_dashboard.pytest_plugin"
```

This registers `qa_dashboard.pytest_plugin` as a pytest plugin
automatically when the package is installed. Users don't need to
add `-p qa_dashboard` to their `pytest.ini` if they want the plugin
always-on; if they want opt-in, they don't add the entry point and
register via `-p` only when needed.

We use the entry-point approach (always-on once installed), with an
escape hatch via `--qa-dashboard-no-report` to skip HTML generation
in CI when only artifacts are needed.

## Dependencies

Required:
- `pytest >= 7.0`
- `mitmproxy >= 11.0` (for the addon's mitmproxy API)

Optional:
- `Pillow >= 10.0` (only if `--qa-dashboard-screenshot-max-width` is
  set; otherwise screenshots are written as-is)

NOT used (do not add):
- `jinja2` — stdlib `string.Template` is enough
- `requests` / `httpx` — no HTTP calls from the plugin
- `pydantic` — manual validation in `schemas.py` is enough at our scale
- `click` / `typer` — stdlib `argparse` is enough for the CLI

If you find yourself wanting to add a dependency, stop and ask.

## Versioning

Semantic versioning. Stable public API after 1.0. Until then, 0.x with
clear changelogs.

The "public API" surface is:

- The `step` fixture and `StepTracker` class API
- The pytest CLI options (`--qa-dashboard-*`)
- The on-disk output schema (in `DATA_CONTRACTS.md`)
- The CLI command (`python -m qa_dashboard`)

Internal modules can change freely between 0.x releases.
