# Packaging & Integration

How `qa-dashboard` ships and how downstream projects adopt it.

## Package shape

```
qa-dashboard/
├── pyproject.toml
├── README.md                    (PyPI front page)
├── LICENSE                      (MIT recommended; ask user)
├── CHANGELOG.md
├── src/qa_dashboard/
│   └── ... (everything in ARCHITECTURE.md)
└── tests/
    └── ...
```

### `pyproject.toml`

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "qa-dashboard"
version = "0.1.0"
description = "Suite-level pytest HTML dashboard with mitmproxy capture, steps, and screenshots."
readme = "README.md"
requires-python = ">=3.10"
license = { text = "MIT" }
authors = [{ name = "<team name>" }]
classifiers = [
    "Framework :: Pytest",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Topic :: Software Development :: Testing",
]
dependencies = [
    "pytest>=7.0",
    "mitmproxy>=11.0",
]

[project.optional-dependencies]
imaging = ["Pillow>=10.0"]
dev = ["pytest-cov", "ruff", "mypy"]

[project.entry-points.pytest11]
qa_dashboard = "qa_dashboard.pytest_plugin"

[project.scripts]
qa-dashboard = "qa_dashboard.cli:main"

[tool.hatch.build.targets.wheel]
packages = ["src/qa_dashboard"]
```

The `pytest11` entry point is critical — it's how pytest auto-discovers
the plugin once `qa-dashboard` is installed. No `-p qa_dashboard` flag
needed unless the user disabled auto-discovery.

## Versioning policy

Semantic versioning. Until 1.0, treat 0.x as breaking-change-allowed
within minor versions, but document every breaking change in
CHANGELOG.md.

After 1.0:
- MAJOR: breaking changes to schemas, fixture APIs, or CLI options
- MINOR: new features, additive schema changes
- PATCH: bug fixes, doc improvements

Schema version (`schema_version` in JSON files) is independent of
package version but tracks roughly with major bumps.

## Adopting in a project

Three integration tiers.

### Tier 1 — Zero code changes (basic usage)

```bash
pip install qa-dashboard
```

Add to `pytest.ini` or `pyproject.toml`:

```ini
[pytest]
addopts = --qa-dashboard-mitm-port=8080
```

Then `pytest tests/` produces `captures/run_<timestamp>/index.html`.

What you get:
- All tests listed with pass/fail/skip
- Network flows captured per test
- Console logs per test
- Pytest's own outcome detail (longrepr, traceback)

What you don't get:
- Step-by-step granularity (need the `step` fixture for that)
- Custom screenshots (need to opt in)

### Tier 2 — Steps and screenshots (recommended)

In any test that wants the full experience:

```python
def test_login_smoke(driver, step):
    with step("Launch app"):
        driver.launch_app()
        step.screenshot(driver.get_screenshot_as_png(), label="splash")

    with step("Tap sign in"):
        driver.find_element(By.ID, "signin_btn").click()
        step.screenshot(driver.get_screenshot_as_png())

    with step("Enter credentials"):
        # ...

    with step("Verify home renders"):
        assert driver.find_element(By.ID, "home").is_displayed()
        step.screenshot(driver.get_screenshot_as_png(), label="home ready")
```

The `step` fixture is auto-injected by the plugin. No imports needed.

Sub-steps optional:

```python
with step("Verify home renders") as s:
    s.substep("Wait for splash dismissed", lambda: wait_for_splash_gone())
    s.substep("Assert ≥ 5 tiles visible", lambda: assert_tiles())
```

`s.substep(name, callable)` runs the callable, times it, marks pass/fail
based on exceptions, and records it under the active step.

### Tier 3 — Custom device/app metadata

For meaningful Environment tab content, projects record device + app
info via a hook:

```python
# In your conftest.py
@pytest.fixture(scope="function")
def driver_setup(qa_dashboard_test, ...):
    driver = create_driver(...)
    qa_dashboard_test.set_device({
        "platform": driver.capabilities["platformName"],
        "platform_version": driver.capabilities["platformVersion"],
        "model": driver.capabilities["deviceName"],
    })
    qa_dashboard_test.set_app({
        "package": driver.capabilities["appPackage"],
        "version": get_app_version(driver),
    })
    yield driver
    driver.quit()
```

`qa_dashboard_test` is another auto-injected fixture exposing per-test
metadata setters.

## Public API surface

These are stable; renames require a major version bump:

### Fixtures (auto-injected)
- `step` — the StepTracker
- `qa_dashboard_test` — per-test metadata setter

### StepTracker methods
- `step(name: str, **kwargs)` → context manager
- `step.screenshot(png_bytes: bytes, label: str = "")` (inside `with step():`)
- `step.substep(name: str, fn: Callable)` (inside `with step():`)
- `step.skip(name: str, reason: str)` (top-level, marks a step as skipped)

### qa_dashboard_test methods
- `set_device(d: dict)`
- `set_app(d: dict)`
- `set_tags(tags: list[str])`
- `attach(filename: str, data: bytes, mime: str = ...)`

### CLI
- `qa-dashboard <run-dir>` — regenerate HTML
- `qa-dashboard --help`

### Pytest options
- `--qa-dashboard-dir`
- `--qa-dashboard-mitm-port`
- `--qa-dashboard-mitm-skip`
- `--qa-dashboard-host-filter`
- `--qa-dashboard-screenshot-on-fail`
- `--qa-dashboard-no-report`
- `--qa-dashboard-pretty`

### Output schema
- `manifest.json` shape (DATA_CONTRACTS.md section 1)
- `tests/<test_id>.json` shape (section 2)
- Directory layout (ARCHITECTURE.md)

Anything not in the above is internal and may change between minor
versions.

## Internal-private API

These exist but users should NOT depend on them:

- `qa_dashboard.bundle.builder` — used by the CLI
- `qa_dashboard.report.generator` — used by the plugin
- `qa_dashboard.capture.mitm_addon` — used by the manager
- Anything in `_private/` subdirectories

If a user needs to extend behaviour beyond what the public API
allows, file an issue rather than reaching into internals.

## Compatibility matrix

| Python | pytest | mitmproxy | Status |
|---|---|---|---|
| 3.10 | 7.x, 8.x | 11.x | supported |
| 3.11 | 7.x, 8.x | 11.x | supported |
| 3.12 | 7.x, 8.x | 11.x | supported (primary CI target) |
| 3.13 | 8.x | 12.x | best-effort, untested |

## CI integration

For GitHub Actions:

```yaml
- name: Run tests with qa-dashboard
  run: pytest tests/

- name: Upload dashboard
  if: always()
  uses: actions/upload-artifact@v4
  with:
    name: qa-dashboard-${{ github.run_number }}
    path: captures/run_*/
    retention-days: 30
```

For Jenkins, archive the directory as a build artifact and serve via
the Jenkins HTML publisher plugin pointed at `captures/run_*/index.html`.

## Migrating an existing project from `mitm_report.py`

1. `pip install qa-dashboard`
2. Add `qa_dashboard` is auto-loaded (no pytest.ini change needed)
3. Keep `mitm_addon.py` for now; the plugin will start its own
   mitmdump. If both run on port 8080, ports clash — set
   `--qa-dashboard-mitm-port=8081` and update device proxy config,
   OR remove the old `mitm_proxy` fixture from `conftest.py` and let
   the plugin manage it.
4. Existing test files keep working. Optionally migrate them to use
   the `step` fixture (Tier 2).
5. After one successful run, archive or delete `mitm_report.py` and
   the existing `mitm_proxy` fixture if they're not needed elsewhere.

The migration is non-destructive. Two reports coexist until the user
decides to clean up.

## Publishing to PyPI

When ready:

```bash
pip install build twine
python -m build
twine upload dist/*
```

For early development, publish to TestPyPI first:

```bash
twine upload --repository testpypi dist/*
pip install --index-url https://test.pypi.org/simple/ qa-dashboard
```

If publishing to a private index (corporate Artifactory, etc.),
configure `~/.pypirc` accordingly. Not in scope for this spec — ask
the user.
