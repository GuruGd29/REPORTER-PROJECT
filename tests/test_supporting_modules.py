"""Unit tests for supporting modules that had 0% or low coverage.

Covers:
  - _manifest.ManifestWriter + collect_environment + collect_source
  - _log_capture.JsonlLogHandler
  - _auto_screenshot.auto_screenshot_for / _try_extract
  - fixtures.StepTracker (step, screenshot, substep, skip, finalize)
  - fixtures._png_dimensions
  - bundle.builder.build_test_record (_read_flows, _read_console)
  - capture.step_channel.StepChannel
  - _paths helpers (iso_from_epoch, make_run_dir)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# _manifest
# ---------------------------------------------------------------------------


class TestManifestWriter:
    def _make(self, tmp_path: Path, pretty: bool = True):
        from qa_dashboard._manifest import ManifestWriter

        return ManifestWriter(
            run_dir=tmp_path,
            run_id="run_test_001",
            config={"mitm_port": 8080},
            pretty=pretty,
        )

    def test_flush_creates_file(self, tmp_path):
        w = self._make(tmp_path)
        w.flush()
        assert (tmp_path / "manifest.json").exists()

    def test_initial_fields(self, tmp_path):
        w = self._make(tmp_path)
        w.flush()
        data = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
        assert data["status"] == "in_progress"
        assert data["run_id"] == "run_test_001"
        assert data["schema_version"] == 1
        assert data["summary"]["total"] == 0

    def test_add_pass_increments_summary(self, tmp_path):
        w = self._make(tmp_path)
        w.flush()
        _add_test(w, "t001", "pass")
        data = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
        assert data["summary"]["total"] == 1
        assert data["summary"]["passed"] == 1
        assert data["summary"]["pass_rate"] == 1.0

    def test_add_fail_increments_summary(self, tmp_path):
        w = self._make(tmp_path)
        w.flush()
        _add_test(w, "t001", "fail")
        data = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
        assert data["summary"]["failed"] == 1

    def test_add_error_increments_summary(self, tmp_path):
        w = self._make(tmp_path)
        w.flush()
        _add_test(w, "t001", "error")
        data = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
        assert data["summary"]["error"] == 1

    def test_add_skip_increments_summary(self, tmp_path):
        w = self._make(tmp_path)
        w.flush()
        _add_test(w, "t001", "skip")
        data = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
        assert data["summary"]["skipped"] == 1

    def test_finalize_status_pass(self, tmp_path):
        w = self._make(tmp_path)
        w.flush()
        _add_test(w, "t001", "pass")
        w.finalize()
        data = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
        assert data["status"] == "pass"
        assert data["ended_at"] is not None
        assert isinstance(data["duration_ms"], int)

    def test_finalize_status_fail(self, tmp_path):
        w = self._make(tmp_path)
        w.flush()
        _add_test(w, "t001", "fail")
        w.finalize()
        data = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
        assert data["status"] == "fail"

    def test_finalize_status_error_takes_priority_over_fail(self, tmp_path):
        w = self._make(tmp_path)
        w.flush()
        _add_test(w, "t001", "fail")
        _add_test(w, "t002", "error")
        w.finalize()
        data = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
        assert data["status"] == "error"

    def test_compact_json_when_pretty_false(self, tmp_path):
        w = self._make(tmp_path, pretty=False)
        w.flush()
        text = (tmp_path / "manifest.json").read_text(encoding="utf-8")
        assert text.count("\n") < 3  # compact = single line

    def test_started_at_accessor(self, tmp_path):
        w = self._make(tmp_path)
        started = w.started_at()
        assert started.endswith("Z")  # ISO format

    def test_pass_rate_rounds_to_three_decimals(self, tmp_path):
        w = self._make(tmp_path)
        w.flush()
        _add_test(w, "t001", "pass")
        _add_test(w, "t002", "pass")
        _add_test(w, "t003", "fail")
        data = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
        assert data["summary"]["pass_rate"] == pytest.approx(0.667, abs=0.001)


def _add_test(writer, test_id: str, status: str) -> None:
    writer.add_test_summary(
        {
            "test_id": test_id,
            "nodeid": f"x::{test_id}",
            "name": test_id,
            "file": "x.py",
            "status": status,
            "started_at": "2026-01-01T00:00:00.000Z",
            "duration_ms": 100,
            "step_count": 0,
            "flow_count": 0,
            "screenshot_count": 0,
            "tags": [],
            "error_summary": None,
        }
    )


class TestCollectHelpers:
    def test_collect_environment_has_required_keys(self):
        from qa_dashboard._manifest import collect_environment

        env = collect_environment()
        for key in ("python", "platform", "qa_dashboard"):
            assert key in env, f"missing key {key!r}"

    def test_collect_source_has_required_keys(self):
        from qa_dashboard._manifest import collect_source

        src = collect_source()
        for key in ("branch", "commit", "trigger"):
            assert key in src, f"missing key {key!r}"

    def test_collect_source_trigger_ci(self, monkeypatch):
        from qa_dashboard._manifest import collect_source

        monkeypatch.setenv("CI", "true")
        monkeypatch.delenv("QA_DASHBOARD_TRIGGER", raising=False)
        src = collect_source()
        assert src["trigger"] == "ci"

    def test_collect_source_trigger_local(self, monkeypatch):
        from qa_dashboard._manifest import collect_source

        monkeypatch.delenv("CI", raising=False)
        monkeypatch.delenv("QA_DASHBOARD_TRIGGER", raising=False)
        src = collect_source()
        assert src["trigger"] == "local"

    def test_collect_source_trigger_explicit(self, monkeypatch):
        from qa_dashboard._manifest import collect_source

        monkeypatch.setenv("QA_DASHBOARD_TRIGGER", "webhook")
        src = collect_source()
        assert src["trigger"] == "webhook"


# ---------------------------------------------------------------------------
# _log_capture
# ---------------------------------------------------------------------------


class TestJsonlLogHandler:
    def test_emit_writes_structured_line(self, tmp_path):
        from qa_dashboard._log_capture import JsonlLogHandler

        path = tmp_path / "_logs" / "t001.jsonl"
        path.parent.mkdir(parents=True)
        handler = JsonlLogHandler(path)
        logger = logging.getLogger("_qa_test_jsonl_unique")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.warning("test message")
        logger.removeHandler(handler)
        handler.close()

        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        obj = json.loads(lines[0])
        assert obj["message"] == "test message"
        assert obj["level"] == "WARNING"
        assert obj["logger"] == "_qa_test_jsonl_unique"
        assert "ts" in obj

    def test_multiple_messages(self, tmp_path):
        from qa_dashboard._log_capture import JsonlLogHandler

        path = tmp_path / "t.jsonl"
        handler = JsonlLogHandler(path)
        logger = logging.getLogger("_qa_multi_unique")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.info("msg1")
        logger.error("msg2")
        logger.removeHandler(handler)
        handler.close()

        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2

    def test_close_is_idempotent(self, tmp_path):
        from qa_dashboard._log_capture import JsonlLogHandler

        path = tmp_path / "t.jsonl"
        handler = JsonlLogHandler(path)
        handler.close()
        handler.close()  # should not raise


# ---------------------------------------------------------------------------
# _auto_screenshot
# ---------------------------------------------------------------------------


class TestAutoScreenshot:
    def test_returns_none_for_empty_funcargs(self):
        from qa_dashboard._auto_screenshot import auto_screenshot_for

        class Item:
            funcargs: dict = {}

        assert auto_screenshot_for(Item()) is None

    def test_returns_none_when_no_driver_fixture(self):
        from qa_dashboard._auto_screenshot import auto_screenshot_for

        class Item:
            funcargs = {"x": 123, "s": "str"}

        assert auto_screenshot_for(Item()) is None

    def test_found_via_driver_preferred_name(self):
        from qa_dashboard._auto_screenshot import auto_screenshot_for

        class FakeDriver:
            def get_screenshot_as_png(self) -> bytes:
                return b"\x89PNG selenium"

        class Item:
            funcargs = {"driver": FakeDriver()}

        assert auto_screenshot_for(Item()) == b"\x89PNG selenium"

    def test_found_via_page_preferred_name(self):
        from qa_dashboard._auto_screenshot import auto_screenshot_for

        class FakePage:
            def screenshot(self) -> bytes:
                return b"\x89PNG playwright"

        class Item:
            funcargs = {"page": FakePage()}

        assert auto_screenshot_for(Item()) == b"\x89PNG playwright"

    def test_found_via_browser_preferred_name(self):
        from qa_dashboard._auto_screenshot import auto_screenshot_for

        class FakeBrowser:
            def screenshot(self) -> bytes:
                return b"\x89PNG browser"

        class Item:
            funcargs = {"browser": FakeBrowser()}

        assert auto_screenshot_for(Item()) == b"\x89PNG browser"

    def test_fallback_scan_finds_driver_object(self):
        from qa_dashboard._auto_screenshot import auto_screenshot_for

        class FakeDriver:
            def get_screenshot_as_png(self) -> bytes:
                return b"\x89PNG fallback"

        class Item:
            funcargs = {"my_custom_driver": FakeDriver()}

        assert auto_screenshot_for(Item()) == b"\x89PNG fallback"

    def test_screenshot_method_raises_returns_none(self):
        from qa_dashboard._auto_screenshot import auto_screenshot_for

        class BrokenDriver:
            def get_screenshot_as_png(self) -> bytes:
                raise RuntimeError("crashed")

        class Item:
            funcargs = {"driver": BrokenDriver()}

        assert auto_screenshot_for(Item()) is None

    def test_no_funcargs_attribute_returns_none(self):
        from qa_dashboard._auto_screenshot import auto_screenshot_for

        class Item:
            pass

        assert auto_screenshot_for(Item()) is None

    def test_screenshot_returns_non_bytes_is_ignored(self):
        from qa_dashboard._auto_screenshot import auto_screenshot_for

        class BadPage:
            def screenshot(self):
                return "not bytes"

        class Item:
            funcargs = {"page": BadPage()}

        assert auto_screenshot_for(Item()) is None


# ---------------------------------------------------------------------------
# fixtures.StepTracker + _png_dimensions
# ---------------------------------------------------------------------------


class TestPngDimensions:
    def test_valid_png_header(self):
        from qa_dashboard.fixtures import _png_dimensions

        # PNG header + IHDR chunk (width=100, height=200)
        header = b"\x89PNG\r\n\x1a\n"
        # IHDR chunk: 4-byte length, 4-byte type, 4-byte width, 4-byte height
        ihdr = b"\x00\x00\x00\r" + b"IHDR"
        width_bytes = (100).to_bytes(4, "big")
        height_bytes = (200).to_bytes(4, "big")
        data = header + ihdr + width_bytes + height_bytes + b"\x00" * 100
        w, h = _png_dimensions(data)
        assert w == 100
        assert h == 200

    def test_invalid_magic_returns_none(self):
        from qa_dashboard.fixtures import _png_dimensions

        w, h = _png_dimensions(b"not a png" + b"\x00" * 20)
        assert w is None
        assert h is None

    def test_too_short_returns_none(self):
        from qa_dashboard.fixtures import _png_dimensions

        w, h = _png_dimensions(b"\x89PNG")
        assert w is None
        assert h is None


class TestStepTracker:
    def _make_tracker(self, tmp_path: Path):
        from qa_dashboard.capture.step_channel import StepChannel
        from qa_dashboard.fixtures import StepTracker

        (tmp_path / "assets" / "screenshots").mkdir(parents=True)
        channel = StepChannel(tmp_path)
        return StepTracker("t001_test", tmp_path, channel)

    def test_step_context_manager_pass(self, tmp_path):
        tracker = self._make_tracker(tmp_path)
        with tracker.step("do thing"):
            pass
        assert len(tracker._steps) == 1
        assert tracker._steps[0]["name"] == "do thing"
        assert tracker._steps[0]["status"] == "pass"

    def test_call_syntax_alias(self, tmp_path):
        tracker = self._make_tracker(tmp_path)
        with tracker("click button"):
            pass
        assert tracker._steps[0]["name"] == "click button"

    def test_step_context_manager_fail(self, tmp_path):
        tracker = self._make_tracker(tmp_path)
        with pytest.raises(ValueError), tracker.step("bad step"):
            raise ValueError("oops")
        assert tracker._steps[0]["status"] == "fail"
        assert tracker._steps[0]["error"]["type"] == "ValueError"
        assert tracker._steps[0]["error"]["message"] == "oops"
        assert tracker._steps[0]["error"]["traceback"] is not None

    def test_multiple_steps(self, tmp_path):
        tracker = self._make_tracker(tmp_path)
        with tracker.step("s1"):
            pass
        with tracker.step("s2"):
            pass
        assert len(tracker._steps) == 2
        assert tracker._steps[0]["id"] == 1
        assert tracker._steps[1]["id"] == 2

    def test_substep_pass(self, tmp_path):
        tracker = self._make_tracker(tmp_path)
        with tracker.step("parent"):
            result = tracker.substep("child", lambda: 99)
        assert result == 99
        assert len(tracker._steps[0]["substeps"]) == 1
        assert tracker._steps[0]["substeps"][0]["status"] == "pass"

    def test_substep_fail(self, tmp_path):
        tracker = self._make_tracker(tmp_path)
        with pytest.raises(RuntimeError), tracker.step("parent"):
            tracker.substep("child", lambda: (_ for _ in ()).throw(RuntimeError("sub-fail")))
        assert tracker._steps[0]["substeps"][0]["status"] == "fail"

    def test_substep_none_fn(self, tmp_path):
        tracker = self._make_tracker(tmp_path)
        with tracker.step("parent"):
            tracker.substep("noted", None)
        assert tracker._steps[0]["substeps"][0]["name"] == "noted"

    def test_substep_outside_step_raises(self, tmp_path):
        tracker = self._make_tracker(tmp_path)
        with pytest.raises(RuntimeError, match="outside"):
            tracker.substep("orphan", None)

    def test_skip_step(self, tmp_path):
        tracker = self._make_tracker(tmp_path)
        tracker.skip("skipped step", "not ready")
        assert len(tracker._steps) == 1
        assert tracker._steps[0]["status"] == "skip"
        assert tracker._steps[0]["skip_reason"] == "not ready"

    def test_screenshot_saved_to_disk(self, tmp_path):
        tracker = self._make_tracker(tmp_path)
        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        with tracker.step("capture"):
            shot_id = tracker.screenshot(fake_png, label="my shot")
        result = tracker.finalize()
        assert len(result["screenshots"]) == 1
        shot = result["screenshots"][0]
        assert shot["id"] == shot_id
        assert shot["label"] == "my shot"
        assert (tmp_path / "assets" / "screenshots" / shot["filename"]).exists()

    def test_screenshot_outside_step(self, tmp_path):
        tracker = self._make_tracker(tmp_path)
        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        tracker.screenshot(fake_png)
        result = tracker.finalize()
        assert len(result["screenshots"]) == 1
        assert result["screenshots"][0]["step_id"] is None

    def test_finalize_returns_steps_and_screenshots(self, tmp_path):
        tracker = self._make_tracker(tmp_path)
        with tracker.step("s"):
            pass
        out = tracker.finalize()
        assert "steps" in out
        assert "screenshots" in out
        assert len(out["steps"]) == 1

    def test_screenshot_callback_property(self, tmp_path):
        def fake_cb() -> bytes:
            return b"\x89PNG"

        tracker = self._make_tracker(tmp_path)
        tracker.set_screenshot_callback(fake_cb)
        assert tracker.screenshot_callback is fake_cb

    def test_set_screenshot_callback(self, tmp_path):
        def fake_cb() -> bytes:
            return b"\x89PNG"

        tracker = self._make_tracker(tmp_path)
        tracker.set_screenshot_callback(fake_cb)
        assert tracker.screenshot_callback is fake_cb

    def test_current_step_property(self, tmp_path):
        tracker = self._make_tracker(tmp_path)
        assert tracker.current_step is None
        with tracker.step("active"):
            assert tracker.current_step is not None
            assert tracker.current_step["name"] == "active"
        assert tracker.current_step is None


# ---------------------------------------------------------------------------
# bundle.builder
# ---------------------------------------------------------------------------


class TestBuildTestRecord:
    def _kwargs(self, tmp_path: Path) -> dict:
        for d in ("tests", "_flows", "_logs"):
            (tmp_path / d).mkdir(exist_ok=True)
        return dict(
            test_id="t001_test_foo",
            nodeid="tests/test_x.py::test_foo",
            name="test_foo",
            file="tests/test_x.py",
            line=10,
            status="pass",
            started_at="2026-01-01T00:00:00.000Z",
            ended_at="2026-01-01T00:00:01.000Z",
            duration_ms=1000,
            tags=["smoke"],
            parameters=None,
            outcome={
                "phase": "call",
                "longrepr": None,
                "traceback_summary": None,
                "stdout_tail": "",
                "stderr_tail": "",
            },
            step_data={"steps": [], "screenshots": []},
            run_dir=tmp_path,
        )

    def test_minimal_record_fields(self, tmp_path):
        from qa_dashboard.bundle.builder import build_test_record

        rec = build_test_record(**self._kwargs(tmp_path))
        assert rec["test_id"] == "t001_test_foo"
        assert rec["status"] == "pass"
        assert rec["schema_version"] == 1
        assert rec["flows"] == []
        assert rec["console"] == []

    def test_reads_flows_from_disk(self, tmp_path):
        from qa_dashboard.bundle.builder import build_test_record

        kw = self._kwargs(tmp_path)
        flows_path = tmp_path / "_flows" / "t001_test_foo.jsonl"
        flows_path.write_text(
            '{"id": 1, "method": "GET", "url": "https://x.com", "step_id": null}\n',
            encoding="utf-8",
        )
        rec = build_test_record(**kw)
        assert len(rec["flows"]) == 1
        assert rec["flows"][0]["method"] == "GET"

    def test_reads_console_from_disk(self, tmp_path):
        from qa_dashboard.bundle.builder import build_test_record

        kw = self._kwargs(tmp_path)
        logs_path = tmp_path / "_logs" / "t001_test_foo.jsonl"
        logs_path.write_text(
            '{"ts": "2026-01-01T00:00:00.000Z", "level": "INFO", "logger": "root", "message": "hi"}\n',
            encoding="utf-8",
        )
        rec = build_test_record(**kw)
        assert len(rec["console"]) == 1
        assert rec["console"][0]["message"] == "hi"

    def test_warning_level_normalized_to_warn(self, tmp_path):
        from qa_dashboard.bundle.builder import build_test_record

        kw = self._kwargs(tmp_path)
        logs_path = tmp_path / "_logs" / "t001_test_foo.jsonl"
        logs_path.write_text(
            '{"ts": "2026-01-01T00:00:00.000Z", "level": "WARNING", "logger": "root", "message": "w"}\n',
            encoding="utf-8",
        )
        rec = build_test_record(**kw)
        assert rec["console"][0]["level"] == "WARN"

    def test_flow_step_ids_linked_to_steps(self, tmp_path):
        from qa_dashboard.bundle.builder import build_test_record

        kw = self._kwargs(tmp_path)
        flows_path = tmp_path / "_flows" / "t001_test_foo.jsonl"
        flows_path.write_text(
            '{"id": 1, "method": "GET", "url": "https://x.com", "step_id": 1}\n',
            encoding="utf-8",
        )
        kw = self._kwargs(tmp_path)
        kw["step_data"] = {
            "steps": [
                {
                    "id": 1,
                    "name": "s1",
                    "status": "pass",
                    "started_at": "2026-01-01T00:00:00.000Z",
                    "ended_at": "2026-01-01T00:00:01.000Z",
                    "duration_ms": 1000,
                    "substeps": [],
                    "screenshot_ids": [],
                    "flow_ids": [],
                    "error": None,
                    "skip_reason": None,
                }
            ],
            "screenshots": [],
        }
        rec = build_test_record(**kw)
        assert 1 in rec["steps"][0]["flow_ids"]

    def test_device_and_app_attached(self, tmp_path):
        from qa_dashboard.bundle.builder import build_test_record

        kw = self._kwargs(tmp_path)
        kw["device"] = {"name": "Pixel 7"}
        kw["app"] = {"version": "2.0.0"}
        rec = build_test_record(**kw)
        assert rec["device"]["name"] == "Pixel 7"
        assert rec["app"]["version"] == "2.0.0"

    def test_ignores_malformed_jsonl_lines(self, tmp_path):
        from qa_dashboard.bundle.builder import build_test_record

        kw = self._kwargs(tmp_path)
        flows_path = tmp_path / "_flows" / "t001_test_foo.jsonl"
        flows_path.write_text("not json\n{}\n", encoding="utf-8")
        rec = build_test_record(**kw)
        assert len(rec["flows"]) == 1  # only the valid `{}` line


# ---------------------------------------------------------------------------
# capture.step_channel.StepChannel
# ---------------------------------------------------------------------------


class TestStepChannel:
    def test_set_and_read(self, tmp_path):
        from qa_dashboard.capture.step_channel import StepChannel

        ch = StepChannel(tmp_path)
        ch.set("t001_x", 3)
        test_id, step_id = ch.read()
        assert test_id == "t001_x"
        assert step_id == 3

    def test_clear_removes_file(self, tmp_path):
        from qa_dashboard.capture.step_channel import StepChannel

        ch = StepChannel(tmp_path)
        ch.set("t001_x", 1)
        ch.clear()
        test_id, step_id = ch.read()
        assert test_id is None
        assert step_id is None

    def test_read_returns_none_when_file_missing(self, tmp_path):
        from qa_dashboard.capture.step_channel import StepChannel

        ch = StepChannel(tmp_path)
        test_id, step_id = ch.read()
        assert test_id is None
        assert step_id is None

    def test_step_id_zero_means_no_step(self, tmp_path):
        from qa_dashboard.capture.step_channel import StepChannel

        ch = StepChannel(tmp_path)
        ch.set("t001_x", 0)
        _, step_id = ch.read()
        assert step_id is None  # 0 maps to None

    def test_set_none_test_id_clears(self, tmp_path):
        from qa_dashboard.capture.step_channel import StepChannel

        ch = StepChannel(tmp_path)
        ch.set(None, 0)
        test_id, _ = ch.read()
        assert test_id is None

    def test_path_property(self, tmp_path):
        from qa_dashboard.capture.step_channel import StepChannel

        ch = StepChannel(tmp_path)
        assert ch.path == tmp_path / "current.txt"


# ---------------------------------------------------------------------------
# _paths helpers
# ---------------------------------------------------------------------------


class TestPathsHelpers:
    def test_iso_from_epoch_format(self):
        from qa_dashboard._paths import iso_from_epoch

        result = iso_from_epoch(0.0)
        assert result == "1970-01-01T00:00:00.000Z"

    def test_now_iso_format(self):
        from qa_dashboard._paths import now_iso

        result = now_iso()
        assert result.endswith("Z")
        assert "T" in result

    def test_make_run_dir_creates_dirs(self, tmp_path):
        from qa_dashboard._paths import make_run_dir

        run_id, run_dir = make_run_dir(tmp_path)
        assert run_id.startswith("run_")
        assert run_dir.exists()
        assert (run_dir / "tests").exists()
        assert (run_dir / "_flows").exists()
        assert (run_dir / "_logs").exists()
        assert (run_dir / "assets" / "screenshots").exists()
