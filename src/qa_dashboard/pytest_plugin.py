"""qa-dashboard pytest plugin.

Registers CLI options, manages the run directory, the mitmproxy
subprocess, the step side-channel, console-log capture, and writes a
TestRecord JSON for every test plus a final ``manifest.json``.

HTML generation is performed at ``pytest_sessionfinish`` via
``qa_dashboard.report.generator.generate_index_html`` if available.
"""
from __future__ import annotations

import logging
import os
import sys
import time
import traceback
from collections import OrderedDict
from pathlib import Path
from typing import Any

import pytest

from . import __version__
from ._auto_screenshot import auto_screenshot_for
from ._log_capture import JsonlLogHandler
from ._manifest import ManifestWriter
from ._paths import iso_from_epoch, make_run_dir, make_test_id, now_iso
from .bundle.builder import build_test_record
from .bundle.schemas import BundleValidationError, validate_manifest, validate_test_record
from .capture.mitm_manager import MitmManager
from .capture.step_channel import StepChannel
from .fixtures import StepTracker


_state_key = pytest.StashKey()
log = logging.getLogger("qa_dashboard")


# ---------------------------------------------------------------------------
# CLI options
# ---------------------------------------------------------------------------

def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("qa-dashboard", "qa-dashboard reporting")
    group.addoption(
        "--qa-dashboard-dir", default=None,
        help="Where to write run directories (default: captures)",
    )
    group.addoption(
        "--qa-dashboard-mitm-port", type=int, default=None,
        help="Port for mitmdump (default: 8080)",
    )
    group.addoption(
        "--qa-dashboard-mitm-skip", action="store_true", default=False,
        help="Run without mitmproxy (network tab empty)",
    )
    group.addoption(
        "--qa-dashboard-host-filter", default=None,
        help="Only capture flows whose host matches this substring",
    )
    group.addoption(
        "--qa-dashboard-screenshot-on-fail", default=None,
        help="If true and the step fixture's screenshot_callback is set, "
             "auto-capture a screenshot at failure",
    )
    group.addoption(
        "--qa-dashboard-no-report", action="store_true", default=False,
        help="Skip HTML generation (JSON artifacts only)",
    )
    group.addoption(
        "--qa-dashboard-pretty", default=None,
        help="Pretty-print JSON output (default: true)",
    )
    group.addoption(
        "--qa-dashboard-disable", action="store_true", default=False,
        help="Disable the plugin entirely (useful for nested pytest runs)",
    )
    group.addoption(
        "--qa-dashboard-screenshot-max-width", type=int, default=None,
        help="Downscale screenshots wider than this (requires Pillow)",
    )
    group.addoption(
        "--qa-dashboard-brand-color", default=None,
        help="Brand accent color for the HTML report (e.g. #1d4ed8)",
    )


def _env_or(name: str, default: Any) -> Any:
    v = os.environ.get(name)
    return v if v is not None else default


def _bool(s: Any, default: bool) -> bool:
    if s is None:
        return default
    if isinstance(s, bool):
        return s
    return str(s).strip().lower() in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# Plugin state
# ---------------------------------------------------------------------------

class _PerTestState:
    __slots__ = ("test_id", "seq", "started_at", "started_perf",
                 "tracker", "log_handler", "outcome",
                 "device", "app", "tags", "duration_ms",
                 "auto_screenshot")

    def __init__(self, test_id: str, seq: int, started_at: str) -> None:
        self.test_id = test_id
        self.seq = seq
        self.started_at = started_at
        self.started_perf = time.perf_counter()
        self.tracker: StepTracker | None = None
        self.log_handler: JsonlLogHandler | None = None
        self.outcome: dict | None = None
        self.device: dict | None = None
        self.app: dict | None = None
        self.tags: list[str] = []
        self.duration_ms: int = 0
        self.auto_screenshot: bytes | None = None


class PluginState:
    def __init__(self, config: pytest.Config) -> None:
        self.config = config
        self.disabled = bool(config.getoption("--qa-dashboard-disable"))

        # Resolve options (CLI > env > ini-style defaults)
        self.dir = Path(
            config.getoption("--qa-dashboard-dir")
            or _env_or("QA_DASHBOARD_DIR", "captures")
        ).resolve()
        port_opt = config.getoption("--qa-dashboard-mitm-port")
        self.mitm_port = int(
            port_opt if port_opt is not None
            else _env_or("QA_DASHBOARD_MITM_PORT", 8080)
        )
        self.mitm_skip = bool(
            config.getoption("--qa-dashboard-mitm-skip")
            or _bool(os.environ.get("QA_DASHBOARD_MITM_SKIP"), False)
        )
        self.host_filter = (
            config.getoption("--qa-dashboard-host-filter")
            or _env_or("QA_DASHBOARD_HOST_FILTER", "")
            or ""
        )
        self.screenshot_on_fail = _bool(
            config.getoption("--qa-dashboard-screenshot-on-fail")
            or _env_or("QA_DASHBOARD_SCREENSHOT_ON_FAIL", "true"),
            True,
        )
        self.no_report = bool(
            config.getoption("--qa-dashboard-no-report")
            or _bool(os.environ.get("QA_DASHBOARD_NO_REPORT"), False)
        )
        self.pretty = _bool(
            config.getoption("--qa-dashboard-pretty")
            or _env_or("QA_DASHBOARD_PRETTY", "true"),
            True,
        )
        self.screenshot_max_width = (
            config.getoption("--qa-dashboard-screenshot-max-width")
            or int(_env_or("QA_DASHBOARD_SCREENSHOT_MAX_WIDTH", 0) or 0)
            or None
        )
        self.brand_color = (
            config.getoption("--qa-dashboard-brand-color")
            or _env_or("QA_DASHBOARD_BRAND_COLOR", None)
        )

        self.run_id: str = ""
        self.run_dir: Path | None = None
        self.manifest: ManifestWriter | None = None
        self.channel: StepChannel | None = None
        self.mitm: MitmManager | None = None
        self._seq = 0
        self._per_test: dict[str, _PerTestState] = {}
        self._failed = False

    # ---- helpers -------------------------------------------------

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def state_for(self, item: pytest.Item) -> _PerTestState | None:
        return self._per_test.get(item.nodeid)

    def create_state(self, item: pytest.Item) -> _PerTestState:
        seq = self.next_seq()
        test_id = make_test_id(seq, item.nodeid)
        st = _PerTestState(test_id, seq, now_iso())
        self._per_test[item.nodeid] = st
        return st


# ---------------------------------------------------------------------------
# Session hooks
# ---------------------------------------------------------------------------

def pytest_configure(config: pytest.Config) -> None:
    if getattr(config, "workerinput", None):
        # xdist worker: parent will manage state
        return
    state = PluginState(config)
    config.stash[_state_key] = state
    if state.disabled:
        return


def pytest_sessionstart(session: pytest.Session) -> None:
    config = session.config
    if _state_key not in config.stash:
        return
    state: PluginState = config.stash[_state_key]
    if state.disabled:
        return
    try:
        state.dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        log.warning("qa-dashboard: cannot create %s: %s; disabling", state.dir, e)
        state.disabled = True
        return
    try:
        run_id, run_dir = make_run_dir(state.dir)
    except Exception as e:
        log.warning("qa-dashboard: failed to create run dir: %s; disabling", e)
        state.disabled = True
        return
    state.run_id = run_id
    state.run_dir = run_dir
    state.channel = StepChannel(run_dir)

    if state.screenshot_max_width:
        try:
            import PIL  # noqa: F401
        except ImportError:
            print(
                "qa-dashboard: --qa-dashboard-screenshot-max-width requires Pillow.\n"
                "Install with: pip install qa-dashboard[imaging]",
                file=sys.stderr,
            )
            state.screenshot_max_width = None

    config_snap = OrderedDict([
        ("mitm_port", state.mitm_port),
        ("host_filter", state.host_filter),
        ("screenshot_on_fail", state.screenshot_on_fail),
        ("command_line", " ".join(sys.argv)),
    ])
    state.manifest = ManifestWriter(run_dir, run_id, config_snap, pretty=state.pretty)
    state.manifest.flush()

    # Start mitmproxy
    if not state.mitm_skip:
        state.mitm = MitmManager(
            run_dir=run_dir,
            port=state.mitm_port,
            host_filter=state.host_filter,
        )
        try:
            state.mitm.start()
        except Exception as e:  # pragma: no cover
            log.warning("qa-dashboard: mitm start failed: %s", e)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    config = session.config
    if _state_key not in config.stash:
        return
    state: PluginState = config.stash[_state_key]
    if state.disabled or state.run_dir is None:
        return
    if state.mitm is not None:
        try:
            state.mitm.stop()
        except Exception:
            pass
    if state.channel is not None:
        try:
            state.channel.clear()
        except Exception:
            pass
    if state.manifest is not None:
        try:
            state.manifest.finalize()
        except Exception:
            log.exception("qa-dashboard: failed to finalize manifest")

    # Optional: HTML generation (Phase 2). Import lazily so Phase 1 works
    # even if the generator isn't ready yet.
    if not state.no_report:
        try:
            from .report.generator import generate_index_html  # type: ignore
        except Exception:
            generate_index_html = None  # type: ignore
        if generate_index_html is not None:
            try:
                generate_index_html(state.run_dir, brand_color=state.brand_color)
                print(
                    f"\nqa-dashboard: report at {state.run_dir / 'index.html'}",
                    file=sys.stderr,
                )
            except Exception:
                log.exception("qa-dashboard: HTML generation failed")
                print(
                    f"\nqa-dashboard: HTML generation failed; "
                    f"JSON artifacts are in {state.run_dir}",
                    file=sys.stderr,
                )
        else:
            print(
                f"\nqa-dashboard: artifacts in {state.run_dir} "
                f"(HTML generator not available)",
                file=sys.stderr,
            )


# ---------------------------------------------------------------------------
# Per-test hooks
# ---------------------------------------------------------------------------

def pytest_runtest_setup(item: pytest.Item) -> None:
    config = item.config
    if _state_key not in config.stash:
        return
    state: PluginState = config.stash[_state_key]
    if state.disabled or state.run_dir is None:
        return
    st = state.create_state(item)
    # Tags from markers
    st.tags = [m.name for m in item.iter_markers()]
    # Side-channel: test active, no step
    try:
        state.channel.set(st.test_id, 0)
    except Exception:
        pass
    # Attach the log handler
    try:
        log_path = state.run_dir / "_logs" / f"{st.test_id}.jsonl"
        handler = JsonlLogHandler(log_path)
        handler.setLevel(logging.DEBUG)
        logging.getLogger().addHandler(handler)
        st.log_handler = handler
    except Exception:
        log.exception("qa-dashboard: failed to attach log handler")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call):
    outcome = yield
    rep: pytest.TestReport = outcome.get_result()
    if _state_key not in item.config.stash:
        return
    state: PluginState = item.config.stash[_state_key]
    if state.disabled:
        return
    st = state.state_for(item)
    if st is None:
        return

    # On failure, grab an auto-screenshot (best-effort, never raises)
    if (rep.when in ("setup", "call") and not rep.passed and not rep.skipped
            and st.auto_screenshot is None):
        try:
            png = auto_screenshot_for(item)
        except Exception:
            png = None
        if png:
            st.auto_screenshot = png

    # Capture outcome on first non-pass, or final call phase
    if rep.when == "call":
        if rep.passed:
            phase_status = "pass"
        elif rep.skipped:
            phase_status = "skip"
        else:
            phase_status = "fail"
        long = str(rep.longrepr) if rep.longrepr else None
        first_line = long.splitlines()[0] if long else None
        st.outcome = OrderedDict([
            ("phase", "call"),
            ("longrepr", long),
            ("traceback_summary", first_line),
            ("stdout_tail", getattr(rep, "capstdout", "") or ""),
            ("stderr_tail", getattr(rep, "capstderr", "") or ""),
            ("_status", phase_status),
        ])
    elif rep.when in ("setup", "teardown") and not rep.passed and st.outcome is None:
        long = str(rep.longrepr) if rep.longrepr else None
        first_line = long.splitlines()[0] if long else None
        st.outcome = OrderedDict([
            ("phase", rep.when),
            ("longrepr", long),
            ("traceback_summary", first_line),
            ("stdout_tail", getattr(rep, "capstdout", "") or ""),
            ("stderr_tail", getattr(rep, "capstderr", "") or ""),
            ("_status", "skip" if rep.skipped else "error"),
        ])


def pytest_runtest_teardown(item: pytest.Item, nextitem) -> None:
    config = item.config
    if _state_key not in config.stash:
        return
    state: PluginState = config.stash[_state_key]
    if state.disabled or state.run_dir is None:
        return
    st = state.state_for(item)
    if st is None:
        # Tests marked with ``@pytest.mark.skip`` short-circuit before our
        # setup hook can run (pytest's skipping plugin uses ``tryfirst``).
        # Create the state lazily so the test still appears in the report.
        st = state.create_state(item)
        st.tags = [m.name for m in item.iter_markers()]
    try:
        _finalize_test(state, item, st)
    except Exception:
        log.exception("qa-dashboard: failed to finalize test %s", item.nodeid)
    finally:
        # Detach the log handler
        if st.log_handler is not None:
            try:
                logging.getLogger().removeHandler(st.log_handler)
                st.log_handler.close()
            except Exception:
                pass
        # Clear the side channel
        if state.channel is not None:
            try:
                state.channel.clear()
            except Exception:
                pass


def _finalize_test(state: PluginState, item: pytest.Item, st: _PerTestState) -> None:
    duration_ms = int((time.perf_counter() - st.started_perf) * 1000)
    st.duration_ms = duration_ms
    ended_at = now_iso()

    # Determine final status
    outcome = st.outcome
    if outcome is None:
        # No outcome was captured. The most common cause is a
        # ``@pytest.mark.skip`` test (pytest's skipping plugin
        # short-circuits before our hooks run). Detect that here.
        skip_marker = item.get_closest_marker("skip") or item.get_closest_marker("skipif")
        if skip_marker is not None:
            reason = skip_marker.kwargs.get("reason") or (
                skip_marker.args[0] if skip_marker.args else "skipped"
            )
            outcome = OrderedDict([
                ("phase", "setup"),
                ("longrepr", f"Skipped: {reason}"),
                ("traceback_summary", f"Skipped: {reason}"),
                ("stdout_tail", ""),
                ("stderr_tail", ""),
                ("_status", "skip"),
            ])
        else:
            outcome = OrderedDict([
                ("phase", "setup"),
                ("longrepr", None),
                ("traceback_summary", None),
                ("stdout_tail", ""),
                ("stderr_tail", ""),
                ("_status", "error"),
            ])
    test_status = outcome.pop("_status")

    # xfailed / xpassed via wasxfail attribute on the report
    # (we collect this from makereport in a simple way; fallback to base status)
    # Optional screenshot-on-fail
    if test_status == "fail" and state.screenshot_on_fail and st.tracker is not None:
        cb = st.tracker.screenshot_callback
        if cb is not None:
            try:
                png = cb()
                if isinstance(png, (bytes, bytearray)):
                    st.tracker.screenshot(bytes(png), label="failure")
            except Exception:
                pass

    step_data = st.tracker.finalize() if st.tracker is not None else {
        "steps": [], "screenshots": [],
    }

    # Auto-screenshot on failure (best-effort). If the user used the
    # ``step`` fixture, attach to the last failing step (or the last
    # step). Otherwise inject a synthetic single-step record so the
    # screenshot has somewhere to live in the report.
    if st.auto_screenshot is not None:
        try:
            _attach_auto_screenshot(state, st, step_data, test_status)
        except Exception:
            log.exception("qa-dashboard: failed to attach auto screenshot")

    parameters = None
    try:
        cs = getattr(item, "callspec", None)
        if cs is not None:
            parameters = {k: _safe_repr(v) for k, v in cs.params.items()}
    except Exception:
        parameters = None

    # File and line
    file_path = ""
    line_no: int | None = None
    try:
        if isinstance(item, pytest.Function):
            file_path = str(Path(item.path).relative_to(Path.cwd())) if hasattr(item, "path") else ""
            try:
                line_no = item.function.__code__.co_firstlineno
            except Exception:
                line_no = None
        else:
            file_path = str(getattr(item, "fspath", "") or "")
    except Exception:
        pass

    record = build_test_record(
        test_id=st.test_id,
        nodeid=item.nodeid,
        name=item.name,
        file=file_path,
        line=line_no,
        status=test_status,
        started_at=st.started_at,
        ended_at=ended_at,
        duration_ms=duration_ms,
        tags=st.tags,
        parameters=parameters,
        outcome=outcome,
        step_data=step_data,
        run_dir=state.run_dir,
        device=st.device,
        app=st.app,
    )

    try:
        validate_test_record(record)
    except BundleValidationError:
        log.exception("qa-dashboard: invalid TestRecord; writing anyway")

    out_path = state.run_dir / "tests" / f"{st.test_id}.json"
    import json
    out_path.write_text(
        json.dumps(record, ensure_ascii=False,
                   indent=2 if state.pretty else None),
        encoding="utf-8",
    )

    error_summary = None
    if test_status in ("fail", "error", "skip"):
        long = outcome.get("longrepr") or ""
        first = long.splitlines()[0] if long else ""
        error_summary = first or None

    summary = OrderedDict([
        ("test_id", st.test_id),
        ("nodeid", item.nodeid),
        ("name", item.name),
        ("file", file_path),
        ("status", test_status),
        ("started_at", st.started_at),
        ("duration_ms", duration_ms),
        ("step_count", len(record["steps"])),
        ("flow_count", len(record["flows"])),
        ("screenshot_count", len(record["screenshots"])),
        ("tags", list(st.tags)),
        ("error_summary", error_summary),
    ])
    if state.manifest is not None:
        state.manifest.add_test_summary(summary)


def _attach_auto_screenshot(state, st, step_data, test_status):
    """Save ``st.auto_screenshot`` to disk and attach to step_data."""
    png = st.auto_screenshot
    if not png:
        return
    # If user didn't use the step fixture, create a synthetic step
    if not step_data["steps"]:
        synthetic_step = OrderedDict([
            ("id", 1),
            ("name", "Test execution"),
            ("status", test_status if test_status in ("pass", "fail", "skip") else "fail"),
            ("started_at", st.started_at),
            ("ended_at", now_iso()),
            ("duration_ms", st.duration_ms),
            ("substeps", []),
            ("screenshot_ids", []),
            ("flow_ids", []),
            ("error", None),
            ("skip_reason", None),
        ])
        step_data["steps"].append(synthetic_step)

    # Find the right step to attach to: last failing step, else last step
    target = None
    for s in reversed(step_data["steps"]):
        if s["status"] == "fail":
            target = s
            break
    if target is None:
        target = step_data["steps"][-1]

    step_id = target["id"]
    # Assign a unique sequence number per-step
    used = len([s for s in step_data["screenshots"] if s.get("step_id") == step_id])
    seq = used + 1
    shot_id = f"{st.test_id}_step_{step_id}_{seq:03d}_auto"
    filename = f"{shot_id}.png"
    path = state.run_dir / "assets" / "screenshots" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)

    # Try to extract PNG width/height
    try:
        from .fixtures import _png_dimensions
        width, height = _png_dimensions(png)
    except Exception:
        width = height = None

    record = OrderedDict([
        ("id", shot_id),
        ("step_id", step_id),
        ("captured_at", now_iso()),
        ("filename", filename),
        ("asset_path", f"assets/screenshots/{filename}"),
        ("width", width),
        ("height", height),
        ("size_bytes", len(png)),
        ("label", "auto-captured on failure" if test_status == "fail" else "auto-captured"),
    ])
    target["screenshot_ids"].append(shot_id)
    step_data["screenshots"].append(record)


def _safe_repr(v: Any) -> Any:
    try:
        import json
        json.dumps(v)
        return v
    except Exception:
        return repr(v)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def step(request: pytest.FixtureRequest) -> StepTracker:
    """Per-test step tracker.

    Use as a context manager:

        def test_thing(step):
            with step("Do something"):
                ...
                step.screenshot(png_bytes, label="caption")
    """
    config = request.config
    state: PluginState = config.stash.get(_state_key, None)  # type: ignore[arg-type]
    if state is None or state.disabled or state.run_dir is None:
        # Plugin disabled — yield a no-op tracker that still works,
        # using a temp dir so screenshot() doesn't crash. The records
        # simply won't be picked up.
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="qa-dashboard-nooptracker-"))
        (tmp / "assets" / "screenshots").mkdir(parents=True)
        channel = StepChannel(tmp)
        (tmp / "current.txt").write_text("", encoding="utf-8")
        return StepTracker("t000_disabled", tmp, channel)

    st = state.state_for(request.node)
    if st is None:
        # setup hook didn't run? Create lazily.
        st = state.create_state(request.node)
    tracker = StepTracker(
        st.test_id, state.run_dir, state.channel,
        max_width=state.screenshot_max_width,
    )
    st.tracker = tracker
    return tracker


@pytest.fixture
def qa_dashboard_test(request: pytest.FixtureRequest):
    """Per-test metadata setter (device, app, tags, attachments)."""
    config = request.config
    state: PluginState = config.stash.get(_state_key, None)  # type: ignore[arg-type]

    class _Meta:
        def set_device(self, d: dict) -> None:
            if state and state.state_for(request.node):
                state.state_for(request.node).device = dict(d)

        def set_app(self, d: dict) -> None:
            if state and state.state_for(request.node):
                state.state_for(request.node).app = dict(d)

        def set_tags(self, tags: list[str]) -> None:
            if state and state.state_for(request.node):
                state.state_for(request.node).tags = list(tags)

        def attach(self, filename: str, data: bytes, mime: str = "application/octet-stream") -> str:
            if not state or state.run_dir is None:
                return ""
            attach_dir = state.run_dir / "assets" / "attachments"
            attach_dir.mkdir(parents=True, exist_ok=True)
            st = state.state_for(request.node)
            test_id = st.test_id if st else "t000"
            safe = filename.replace("/", "_")
            out = attach_dir / f"{test_id}_{safe}"
            out.write_bytes(data)
            return str(out.relative_to(state.run_dir))

    return _Meta()
