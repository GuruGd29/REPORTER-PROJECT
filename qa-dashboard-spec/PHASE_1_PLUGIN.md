# Phase 1 — Pytest plugin and capture pipeline

**Goal:** A working `qa-dashboard` package that, when installed and
enabled, captures everything needed for a report — but does not yet
generate HTML. Phase 1 ends with a directory of JSON artifacts that
the user can inspect.

**Estimated size:** 1 PR. ~800 lines across the package. No HTML
generation yet.

---

## What you're building

After Phase 1:

```bash
pip install -e .                 # the new package
pytest tests/                    # any pytest project
ls captures/run_<timestamp>/
  manifest.json
  current.txt                    (empty after run)
  tests/
    t001_test_foo.json
    t002_test_bar.json
  assets/screenshots/
    t001_step_2_001.png
```

`index.html` does NOT exist yet. That's Phase 2.

---

## Task checklist

Work in order. After each task, the package should still install and
the test suite (in `tests/` of the qa-dashboard repo itself) should
still pass.

### Task 1.1 — Package scaffold

Create `pyproject.toml` per PACKAGING.md. Create `src/qa_dashboard/`
with empty `__init__.py` and stubbed modules per ARCHITECTURE.md.

```bash
pip install -e .
python -c "import qa_dashboard; print(qa_dashboard.__version__)"
# Should print 0.1.0
```

`src/qa_dashboard/__init__.py`:

```python
__version__ = "0.1.0"
```

### Task 1.2 — Pytest plugin skeleton

`src/qa_dashboard/pytest_plugin.py`:

Register hooks:
- `pytest_addoption(parser)` — adds all `--qa-dashboard-*` options
- `pytest_configure(config)` — validates options, sets up run state
- `pytest_sessionstart(session)` — creates run directory, scaffolds manifest
- `pytest_runtest_setup(item)` — writes test_id to current.txt
- `pytest_runtest_makereport(item, call)` — captures outcome (use this
  rather than runtest_teardown for accurate outcome capture)
- `pytest_runtest_teardown(item)` — writes TestRecord, clears current.txt
- `pytest_sessionfinish(session, exitstatus)` — finalizes manifest
  (HTML generation comes in Phase 2; for now just finalize JSON)

Use `config.stash` or a module-level dict to share state across hooks.
Pytest's `config.stash[some_key]` is the canonical pattern.

Verify with a no-op test:

```python
def test_smoke():
    assert 1 + 1 == 2
```

After running `pytest`, `captures/run_<timestamp>/manifest.json` exists
and contains one test entry.

### Task 1.3 — Run directory + manifest

`src/qa_dashboard/_paths.py` (or inline in the plugin):

```python
def make_run_dir(base: Path) -> tuple[str, Path]:
    """Create a unique run directory. Returns (run_id, path)."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    suffix = secrets.token_hex(3)
    run_id = f"run_{ts}_{suffix}"
    path = base / run_id
    path.mkdir(parents=True)
    (path / "tests").mkdir()
    (path / "assets" / "screenshots").mkdir(parents=True)
    (path / "current.txt").write_text("")
    return run_id, path
```

`src/qa_dashboard/_manifest.py`:

```python
class ManifestWriter:
    """Maintains manifest.json across the run, flushing after each test."""
    def __init__(self, run_dir: Path, run_id: str, config: dict): ...
    def init_session(self, env: dict, source: dict) -> None: ...
    def add_test_summary(self, test_summary: dict) -> None: ...
    def finalize(self, status: str, ended_at: str) -> None: ...
```

Validates against DATA_CONTRACTS.md section 1 before writing.

### Task 1.4 — Mitmproxy manager

`src/qa_dashboard/capture/mitm_manager.py`:

Starts mitmdump as a subprocess at `pytest_sessionstart` and stops at
`pytest_sessionfinish`. Passes env vars to the subprocess to tell the
addon where to write its outputs.

```python
class MitmManager:
    def __init__(self, run_dir: Path, port: int, host_filter: str): ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    @property
    def is_running(self) -> bool: ...
```

`start()`:
- spawns `mitmdump -p <port> -s <addon.py> -q`
- sets env vars `QA_DASHBOARD_RUN_DIR`, `QA_DASHBOARD_HOST_FILTER`
- waits up to 5s for the port to be listening (poll with a socket
  connect)
- if it doesn't come up, log loudly and set `is_running = False`,
  but DO NOT raise. The tests should still run; the network tab
  will be empty.

`stop()`:
- sends SIGTERM, waits 3s
- if still alive, sends SIGKILL
- joins the process

Handle the `--qa-dashboard-mitm-skip` option: when true, don't start
mitmdump at all.

### Task 1.5 — The mitmproxy addon (shipped with the package)

`src/qa_dashboard/capture/mitm_addon.py`:

This is the addon that runs in the mitmdump subprocess. It must NOT
import from any other `qa_dashboard.*` module (the subprocess
shouldn't pay the import cost). Stdlib + mitmproxy only.

Behaviour per flow:
1. Read host filter from env, skip if doesn't match
2. Read `current.txt` to get `(test_id, step_id)`
3. Build the Flow dict (per DATA_CONTRACTS.md section 4)
4. If no `test_id` (between tests), drop the flow — we don't
   attribute orphan flows
5. Append the flow to an in-memory list keyed by `test_id`
6. At `pytest_runtest_teardown` time, the parent process tells the
   addon (via writing a sentinel into `current.txt` like
   `"<test_id>\tFLUSH"`) to write that test's flows to a temporary
   file the parent will read.

Actually that's clumsy. Better:

Each flow is written individually to a per-test append-only file:

```
captures/run_<timestamp>/_flows/t001.jsonl
captures/run_<timestamp>/_flows/t002.jsonl
```

One JSON object per line. At teardown, the parent process reads the
file and assembles the test's flows array.

Pros: no IPC, crash-safe, easy to debug.
Cons: opening a new file handle per test. Acceptable.

The addon caches file handles keyed by `test_id` and rotates as
`current.txt` changes.

### Task 1.6 — Side-channel for step tracking

`src/qa_dashboard/capture/step_channel.py`:

```python
class StepChannel:
    def __init__(self, run_dir: Path): ...
    def set(self, test_id: str | None, step_id: int = 0) -> None:
        """Atomically update current.txt."""
        if test_id is None:
            content = ""
        else:
            content = f"{test_id}\t{step_id}"
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, self._path)

    def clear(self) -> None:
        self.set(None)
```

This is used by both the plugin (in setup/teardown) and the
StepTracker (in step enter/exit).

### Task 1.7 — StepTracker fixture

`src/qa_dashboard/fixtures.py`:

```python
class StepTracker:
    def __init__(self, test_id: str, run_dir: Path, channel: StepChannel):
        self._test_id = test_id
        self._run_dir = run_dir
        self._channel = channel
        self._steps: list[dict] = []
        self._current: dict | None = None
        self._screenshot_seq = defaultdict(int)

    @contextmanager
    def step(self, name: str):
        step_id = len(self._steps) + 1
        step = {
            "id": step_id,
            "name": name,
            "status": "pass",  # may be overridden in __exit__
            "started_at": _now_iso(),
            ...
        }
        self._steps.append(step)
        self._current = step
        self._channel.set(self._test_id, step_id)
        try:
            yield self
        except BaseException as e:
            step["status"] = "fail"
            step["error"] = {
                "type": type(e).__name__,
                "message": str(e),
                "traceback": traceback.format_exc(),
            }
            raise
        finally:
            step["ended_at"] = _now_iso()
            step["duration_ms"] = _ms_between(step["started_at"], step["ended_at"])
            self._current = None
            self._channel.set(self._test_id, 0)  # test active, no step

    def screenshot(self, png_bytes: bytes, label: str = "") -> str:
        """Save a screenshot for the current step (or step 0 if none)."""
        step_id = self._current["id"] if self._current else 0
        self._screenshot_seq[step_id] += 1
        seq = self._screenshot_seq[step_id]
        shot_id = f"{self._test_id}_step_{step_id}_{seq:03d}"
        filename = f"{shot_id}.png"
        path = self._run_dir / "assets" / "screenshots" / filename
        path.write_bytes(png_bytes)
        if label:
            (path.parent / f"{shot_id}.label").write_text(label, encoding="utf-8")
        record = {
            "id": shot_id,
            "step_id": step_id if step_id > 0 else None,
            "captured_at": _now_iso(),
            "filename": filename,
            "asset_path": f"assets/screenshots/{filename}",
            "size_bytes": len(png_bytes),
            "label": label,
        }
        if self._current:
            self._current.setdefault("screenshot_ids", []).append(shot_id)
        # Append to a per-test screenshots list maintained on the tracker
        self._screenshots.append(record)
        return shot_id

    def substep(self, name: str, fn=None):
        """Run fn() as a substep, record duration and pass/fail."""
        ...

    def skip(self, name: str, reason: str):
        """Append a skipped step (no execution)."""
        ...

    def finalize(self) -> dict:
        """Return the steps + screenshots data for embedding in the TestRecord."""
        return {
            "steps": self._steps,
            "screenshots": self._screenshots,
        }
```

Register as a pytest fixture in the plugin:

```python
@pytest.fixture(scope="function")
def step(request) -> StepTracker:
    plugin = request.config.stash[_state_key]
    test_id = plugin.current_test_id(request.node)
    tracker = StepTracker(test_id, plugin.run_dir, plugin.channel)
    plugin.register_tracker(request.node, tracker)
    yield tracker
    # The plugin reads the tracker's data in runtest_teardown
```

### Task 1.8 — Console log capture

`src/qa_dashboard/_log_capture.py`:

```python
class JsonlLogHandler(logging.Handler):
    def __init__(self, path: Path):
        super().__init__()
        self._fp = path.open("a", encoding="utf-8")
    def emit(self, record):
        line = json.dumps({
            "ts": _iso_from_epoch(record.created),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }, ensure_ascii=False)
        self._fp.write(line + "\n")
        self._fp.flush()
    def close(self):
        super().close()
        self._fp.close()
```

Attached at `pytest_runtest_setup`, removed at `pytest_runtest_teardown`.
Logs written to `_logs/<test_id>.jsonl`.

### Task 1.9 — TestRecord assembly

`src/qa_dashboard/bundle/builder.py`:

```python
def build_test_record(
    test_id: str,
    nodeid: str,
    outcome: dict,
    started_at: str,
    duration_ms: int,
    run_dir: Path,
    step_data: dict,  # from tracker.finalize()
    device: dict | None,
    app: dict | None,
) -> dict:
    """Assemble a TestRecord per DATA_CONTRACTS.md section 2."""

    flows = _read_flows(run_dir / "_flows" / f"{test_id}.jsonl")
    console = _read_console(run_dir / "_logs" / f"{test_id}.jsonl")

    # Compute flow_ids per step
    flow_ids_by_step = defaultdict(list)
    for f in flows:
        if f.get("step_id") is not None:
            flow_ids_by_step[f["step_id"]].append(f["id"])

    for step in step_data["steps"]:
        step["flow_ids"] = flow_ids_by_step.get(step["id"], [])

    return {
        "schema_version": 1,
        "test_id": test_id,
        "nodeid": nodeid,
        ...
        "steps": step_data["steps"],
        "flows": flows,
        "screenshots": step_data["screenshots"],
        "console": console,
        "device": device,
        "app": app,
    }
```

`src/qa_dashboard/bundle/schemas.py`:

```python
def validate_test_record(record: dict) -> None:
    """Raises BundleValidationError if record violates the schema."""
    ...

def validate_manifest(manifest: dict) -> None: ...
```

Throw clear errors with field paths:

```
BundleValidationError: tests[3].steps[2].status: expected one of ('pass','fail','skip'), got 'banana'
```

### Task 1.10 — Wire it all together in the plugin

The plugin's `pytest_runtest_teardown` hook is the most complex:

```python
def pytest_runtest_teardown(item, nextitem):
    plugin = item.config.stash[_state_key]
    test_id = plugin.get_test_id(item)

    # 1. Get the tracker (may be None if test didn't use the `step` fixture)
    tracker = plugin.get_tracker(item)
    step_data = tracker.finalize() if tracker else {"steps": [], "screenshots": []}

    # 2. Get the outcome captured by pytest_runtest_makereport
    outcome = plugin.get_outcome(item)

    # 3. Build the TestRecord
    record = build_test_record(
        test_id=test_id,
        nodeid=item.nodeid,
        outcome=outcome,
        started_at=plugin.get_started_at(item),
        duration_ms=plugin.get_duration_ms(item),
        run_dir=plugin.run_dir,
        step_data=step_data,
        device=plugin.get_device(item),
        app=plugin.get_app(item),
    )

    # 4. Validate
    validate_test_record(record)

    # 5. Write to disk
    out_path = plugin.run_dir / "tests" / f"{test_id}.json"
    out_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2 if plugin.pretty else None),
        encoding="utf-8"
    )

    # 6. Append summary to manifest
    plugin.manifest.add_test_summary({
        "test_id": test_id,
        "nodeid": item.nodeid,
        ...
    })

    # 7. Clear side-channel
    plugin.channel.clear()
```

Order matters. Don't reorder steps without thinking.

---

## Acceptance criteria (Phase 1 done)

In a fresh project:

```bash
pip install -e /path/to/qa-dashboard
mkdir testproj && cd testproj
cat > test_smoke.py <<EOF
def test_passes():
    assert True

def test_fails():
    assert False, "boom"

def test_uses_steps(step):
    with step("First thing"):
        pass
    with step("Second thing"):
        step.screenshot(b"\\x89PNG\\r\\n\\x1a\\n" + b"\\x00" * 100)
EOF
pytest test_smoke.py
```

Then verify:

1. `captures/run_<timestamp>/` directory exists
2. `manifest.json` exists, validates against schema, contains 3 tests
3. `tests/t001_test_passes.json` exists, validates, shows status=pass
4. `tests/t002_test_fails.json` exists, validates, shows status=fail,
   has the assertion message in `outcome.longrepr`
5. `tests/t003_test_uses_steps.json` exists, validates, has 2 steps,
   1 screenshot
6. `assets/screenshots/t003_step_2_001.png` exists
7. `current.txt` exists and is empty at the end
8. No `index.html` yet (Phase 2)
9. If mitmproxy was set up correctly and tests routed through it,
   flows are captured. If not (no proxy configured), tests still run.
10. The plugin doesn't crash when a test fails — failed tests are
    captured as such, not as plugin errors.

---

## OUT of Phase 1

- `index.html` generation — Phase 2
- The CLI `qa-dashboard` command — Phase 2
- Cross-test joins or aggregations beyond manifest summary — Phase 2
- Screenshot lightbox, network filter UI — Phase 2 (it's all in the HTML)
- Pillow integration for downscaling — Phase 3
- JUnit XML import — out of scope entirely

---

## Questions to ask the user before starting

1. License — MIT, Apache 2.0, or proprietary?
2. PyPI package name available? Check `pip search` or
   `https://pypi.org/project/qa-dashboard/`. If taken, fallback names?
3. Should the package vendor mitmproxy's CA cert installation flow,
   or assume users handle that themselves? (Default: assume users
   handle it; it's a per-project concern.)
4. Python version floor: 3.10 or 3.11?
5. Where should the package live during development — a new repo or
   a folder inside the existing test project?
