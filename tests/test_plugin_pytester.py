"""Pytester-based tests for qa_dashboard.pytest_plugin.

Uses runpytest_inprocess so the plugin code executes in the same Python
process and every line counts toward the coverage report.  Each test
spins up a small inner pytest session in the temp directory that pytester
manages.
"""

from __future__ import annotations

import json
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _first_run_dir(base: Path) -> Path:
    dirs = sorted(base.glob("run_*"))
    assert dirs, f"no run_* dirs under {base}"
    return dirs[0]


def _opts(*extra: str) -> tuple[str, ...]:
    """Base options for every inner run: skip mitm, skip HTML."""
    return ("--qa-dashboard-mitm-skip", "--qa-dashboard-no-report", *extra)


def _load_manifest(run_dir: Path) -> dict:
    return json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))


def _load_first_test(run_dir: Path) -> dict:
    files = sorted((run_dir / "tests").glob("t*.json"))
    assert files, "no test JSON files found"
    return json.loads(files[0].read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Basic lifecycle
# ---------------------------------------------------------------------------


def test_creates_manifest_for_passing_test(pytester):
    pytester.makepyfile("""
        def test_simple():
            assert 1 + 1 == 2
    """)
    result = pytester.runpytest_inprocess(*_opts())
    result.assert_outcomes(passed=1)

    run_dir = _first_run_dir(pytester.path / "captures")
    manifest = _load_manifest(run_dir)

    assert manifest["schema_version"] == 1
    assert manifest["run_id"].startswith("run_")
    assert manifest["status"] == "pass"
    assert manifest["summary"]["total"] == 1
    assert manifest["summary"]["passed"] == 1
    assert manifest["summary"]["failed"] == 0
    assert "environment" in manifest
    assert "source" in manifest


def test_creates_per_test_json(pytester):
    pytester.makepyfile("""
        def test_hello():
            x = 42
            assert x == 42
    """)
    result = pytester.runpytest_inprocess(*_opts())
    result.assert_outcomes(passed=1)

    run_dir = _first_run_dir(pytester.path / "captures")
    rec = _load_first_test(run_dir)

    assert rec["status"] == "pass"
    assert "test_hello" in rec["nodeid"]
    assert rec["duration_ms"] >= 0
    assert "started_at" in rec
    assert "ended_at" in rec
    assert isinstance(rec["steps"], list)
    assert isinstance(rec["flows"], list)
    assert isinstance(rec["console"], list)


def test_generates_html_by_default(pytester):
    pytester.makepyfile("""
        def test_ok():
            pass
    """)
    result = pytester.runpytest_inprocess("--qa-dashboard-mitm-skip")
    result.assert_outcomes(passed=1)

    run_dir = _first_run_dir(pytester.path / "captures")
    assert (run_dir / "index.html").exists()
    html = (run_dir / "index.html").read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html


def test_no_report_skips_html(pytester):
    pytester.makepyfile("""
        def test_ok():
            pass
    """)
    result = pytester.runpytest_inprocess(*_opts())
    result.assert_outcomes(passed=1)

    run_dir = _first_run_dir(pytester.path / "captures")
    assert not (run_dir / "index.html").exists()


def test_custom_output_dir(pytester):
    pytester.makepyfile("""
        def test_ok():
            pass
    """)
    result = pytester.runpytest_inprocess(*_opts("--qa-dashboard-dir=my_reports"))
    result.assert_outcomes(passed=1)

    run_dir = _first_run_dir(pytester.path / "my_reports")
    assert (run_dir / "manifest.json").exists()


def test_disable_skips_all_artifacts(pytester):
    pytester.makepyfile("""
        def test_ok():
            pass
    """)
    result = pytester.runpytest_inprocess("--qa-dashboard-disable")
    result.assert_outcomes(passed=1)

    captures = pytester.path / "captures"
    assert not captures.exists() or not list(captures.glob("run_*"))


# ---------------------------------------------------------------------------
# Test outcomes
# ---------------------------------------------------------------------------


def test_records_failed_test(pytester):
    pytester.makepyfile("""
        def test_fail():
            assert False, "boom"
    """)
    result = pytester.runpytest_inprocess(*_opts())
    result.assert_outcomes(failed=1)

    run_dir = _first_run_dir(pytester.path / "captures")
    manifest = _load_manifest(run_dir)
    assert manifest["status"] == "fail"
    assert manifest["summary"]["failed"] == 1

    rec = _load_first_test(run_dir)
    assert rec["status"] == "fail"
    assert rec["outcome"]["longrepr"] is not None


def test_records_skipped_test(pytester):
    pytester.makepyfile("""
        import pytest

        @pytest.mark.skip(reason="not ready")
        def test_skipped():
            pass
    """)
    result = pytester.runpytest_inprocess(*_opts())
    result.assert_outcomes(skipped=1)

    run_dir = _first_run_dir(pytester.path / "captures")
    manifest = _load_manifest(run_dir)
    assert manifest["summary"]["skipped"] == 1

    rec = _load_first_test(run_dir)
    assert rec["status"] == "skip"


def test_records_error_in_fixture_setup(pytester):
    pytester.makepyfile("""
        import pytest

        @pytest.fixture
        def broken():
            raise RuntimeError("fixture broke")

        def test_with_broken(broken):
            pass
    """)
    result = pytester.runpytest_inprocess(*_opts())
    result.assert_outcomes(errors=1)

    run_dir = _first_run_dir(pytester.path / "captures")
    manifest = _load_manifest(run_dir)
    assert manifest["summary"]["error"] >= 1


def test_mixed_outcomes_summary(pytester):
    pytester.makepyfile("""
        import pytest

        def test_pass():
            assert True

        def test_fail():
            assert False

        @pytest.mark.skip
        def test_skip():
            pass
    """)
    result = pytester.runpytest_inprocess(*_opts())
    result.assert_outcomes(passed=1, failed=1, skipped=1)

    run_dir = _first_run_dir(pytester.path / "captures")
    manifest = _load_manifest(run_dir)
    assert manifest["summary"]["total"] == 3
    assert manifest["summary"]["passed"] == 1
    assert manifest["summary"]["failed"] == 1
    assert manifest["summary"]["skipped"] == 1
    assert len(list((run_dir / "tests").glob("*.json"))) == 3


def test_xfail_test_does_not_break_run(pytester):
    pytester.makepyfile("""
        import pytest

        @pytest.mark.xfail
        def test_expected_fail():
            assert False
    """)
    result = pytester.runpytest_inprocess(*_opts())
    assert result.ret == 0

    run_dir = _first_run_dir(pytester.path / "captures")
    manifest = _load_manifest(run_dir)
    assert manifest["summary"]["total"] == 1


def test_parametrized_tests_all_recorded(pytester):
    pytester.makepyfile("""
        import pytest

        @pytest.mark.parametrize("x,y", [(1, 1), (2, 2), (3, 4)])
        def test_add(x, y):
            assert x == y
    """)
    result = pytester.runpytest_inprocess(*_opts())
    result.assert_outcomes(passed=2, failed=1)

    run_dir = _first_run_dir(pytester.path / "captures")
    manifest = _load_manifest(run_dir)
    assert manifest["summary"]["total"] == 3
    assert len(list((run_dir / "tests").glob("*.json"))) == 3


def test_tags_captured_from_markers(pytester):
    pytester.makeconftest("""
        def pytest_configure(config):
            config.addinivalue_line("markers", "smoke: smoke suite")
            config.addinivalue_line("markers", "regression: regression suite")
    """)
    pytester.makepyfile("""
        import pytest

        @pytest.mark.smoke
        @pytest.mark.regression
        def test_tagged():
            pass
    """)
    result = pytester.runpytest_inprocess(*_opts())
    result.assert_outcomes(passed=1)

    rec = _load_first_test(_first_run_dir(pytester.path / "captures"))
    assert "smoke" in rec["tags"]
    assert "regression" in rec["tags"]


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------


def test_brand_color_appears_in_html(pytester):
    pytester.makepyfile("""
        def test_ok():
            pass
    """)
    result = pytester.runpytest_inprocess(
        "--qa-dashboard-mitm-skip",
        "--qa-dashboard-brand-color=#ff6600",
    )
    result.assert_outcomes(passed=1)

    run_dir = _first_run_dir(pytester.path / "captures")
    html = (run_dir / "index.html").read_text(encoding="utf-8")
    assert "#ff6600" in html


def test_redact_option_sets_env_var(pytester):
    """--qa-dashboard-redact propagates to QA_DASHBOARD_REDACT so the mitm
    subprocess can pick it up before being spawned."""
    pytester.makepyfile("""
        import os

        def test_env():
            assert os.environ.get("QA_DASHBOARD_REDACT") == "x-my-secret"
    """)
    result = pytester.runpytest_inprocess(
        "--qa-dashboard-mitm-skip",
        "--qa-dashboard-no-report",
        "--qa-dashboard-redact=x-my-secret",
    )
    result.assert_outcomes(passed=1)


def test_pretty_false_produces_compact_json(pytester):
    pytester.makepyfile("""
        def test_ok():
            pass
    """)
    result = pytester.runpytest_inprocess(*_opts("--qa-dashboard-pretty=false"))
    result.assert_outcomes(passed=1)

    run_dir = _first_run_dir(pytester.path / "captures")
    text = (run_dir / "manifest.json").read_text(encoding="utf-8")
    # Compact JSON has very few newlines (just the outer one)
    assert text.count("\n") < 5


# ---------------------------------------------------------------------------
# step fixture
# ---------------------------------------------------------------------------


def test_step_fixture_records_steps(pytester):
    pytester.makepyfile("""
        def test_with_steps(step):
            with step("open browser"):
                result = "browser"
            with step("navigate"):
                url = "https://example.com"
    """)
    result = pytester.runpytest_inprocess(*_opts())
    result.assert_outcomes(passed=1)

    rec = _load_first_test(_first_run_dir(pytester.path / "captures"))
    assert len(rec["steps"]) == 2
    assert rec["steps"][0]["name"] == "open browser"
    assert rec["steps"][0]["status"] == "pass"
    assert rec["steps"][1]["name"] == "navigate"


def test_step_fixture_records_failure(pytester):
    pytester.makepyfile("""
        def test_fail_in_step(step):
            with step("bad step"):
                raise ValueError("intentional")
    """)
    result = pytester.runpytest_inprocess(*_opts())
    result.assert_outcomes(failed=1)

    rec = _load_first_test(_first_run_dir(pytester.path / "captures"))
    assert rec["steps"][0]["status"] == "fail"
    assert rec["steps"][0]["error"]["type"] == "ValueError"
    assert rec["steps"][0]["error"]["message"] == "intentional"


def test_step_fixture_works_when_plugin_disabled(pytester):
    pytester.makepyfile("""
        def test_noop(step):
            with step("does something"):
                pass
            assert True
    """)
    result = pytester.runpytest_inprocess("--qa-dashboard-disable")
    result.assert_outcomes(passed=1)


def test_step_substep(pytester):
    pytester.makepyfile("""
        def test_substep(step):
            with step("parent"):
                step.substep("child", lambda: 42)
    """)
    result = pytester.runpytest_inprocess(*_opts())
    result.assert_outcomes(passed=1)

    rec = _load_first_test(_first_run_dir(pytester.path / "captures"))
    assert len(rec["steps"][0]["substeps"]) == 1
    assert rec["steps"][0]["substeps"][0]["name"] == "child"


def test_step_skip_method(pytester):
    pytester.makepyfile("""
        def test_skip_step(step):
            with step("first"):
                pass
            step.skip("skipped step", reason="not applicable")
    """)
    result = pytester.runpytest_inprocess(*_opts())
    result.assert_outcomes(passed=1)

    rec = _load_first_test(_first_run_dir(pytester.path / "captures"))
    assert len(rec["steps"]) == 2
    assert rec["steps"][1]["status"] == "skip"
    assert rec["steps"][1]["skip_reason"] == "not applicable"


# ---------------------------------------------------------------------------
# qa_dashboard_test fixture
# ---------------------------------------------------------------------------


def test_qa_dashboard_test_set_device_and_app(pytester):
    pytester.makepyfile("""
        def test_metadata(qa_dashboard_test):
            qa_dashboard_test.set_device({"name": "iPhone 15", "os": "iOS 17"})
            qa_dashboard_test.set_app({"version": "3.2.1"})
    """)
    result = pytester.runpytest_inprocess(*_opts())
    result.assert_outcomes(passed=1)

    rec = _load_first_test(_first_run_dir(pytester.path / "captures"))
    assert rec["device"]["name"] == "iPhone 15"
    assert rec["app"]["version"] == "3.2.1"


def test_qa_dashboard_test_set_tags(pytester):
    pytester.makepyfile("""
        def test_tags(qa_dashboard_test):
            qa_dashboard_test.set_tags(["alpha", "beta"])
    """)
    result = pytester.runpytest_inprocess(*_opts())
    result.assert_outcomes(passed=1)

    rec = _load_first_test(_first_run_dir(pytester.path / "captures"))
    assert "alpha" in rec["tags"]
    assert "beta" in rec["tags"]


def test_qa_dashboard_test_attach(pytester):
    pytester.makepyfile("""
        def test_attach(qa_dashboard_test):
            path = qa_dashboard_test.attach("report.txt", b"hello world", "text/plain")
            assert path
    """)
    result = pytester.runpytest_inprocess(*_opts())
    result.assert_outcomes(passed=1)

    run_dir = _first_run_dir(pytester.path / "captures")
    attachments = list((run_dir / "assets" / "attachments").glob("*report.txt"))
    assert attachments
    assert attachments[0].read_bytes() == b"hello world"


# ---------------------------------------------------------------------------
# Private helpers (pure unit tests — no inner pytest needed)
# ---------------------------------------------------------------------------


def test_bool_helper_truthy_strings():
    from qa_dashboard.pytest_plugin import _bool

    for v in ("true", "1", "yes", "on", "True", "YES"):
        assert _bool(v, False) is True, f"expected True for {v!r}"


def test_bool_helper_falsy_strings():
    from qa_dashboard.pytest_plugin import _bool

    for v in ("false", "0", "no", "off", "False", "NO"):
        assert _bool(v, True) is False, f"expected False for {v!r}"


def test_bool_helper_none_uses_default():
    from qa_dashboard.pytest_plugin import _bool

    assert _bool(None, True) is True
    assert _bool(None, False) is False


def test_bool_helper_bool_passthrough():
    from qa_dashboard.pytest_plugin import _bool

    assert _bool(True, False) is True
    assert _bool(False, True) is False


def test_env_or_reads_env_var(monkeypatch):
    from qa_dashboard.pytest_plugin import _env_or

    monkeypatch.setenv("_QA_UNIQUE_TEST_KEY_XYZ", "hello")
    assert _env_or("_QA_UNIQUE_TEST_KEY_XYZ", "default") == "hello"


def test_env_or_returns_default_when_unset(monkeypatch):
    from qa_dashboard.pytest_plugin import _env_or

    monkeypatch.delenv("_QA_UNIQUE_TEST_KEY_XYZ", raising=False)
    assert _env_or("_QA_UNIQUE_TEST_KEY_XYZ", "default") == "default"


def test_safe_repr_json_serializable():
    from qa_dashboard.pytest_plugin import _safe_repr

    assert _safe_repr(42) == 42
    assert _safe_repr("hello") == "hello"
    assert _safe_repr([1, 2]) == [1, 2]
    assert _safe_repr({"k": "v"}) == {"k": "v"}


def test_safe_repr_non_serializable_returns_string():
    from qa_dashboard.pytest_plugin import _safe_repr

    class Unserializable:
        def __repr__(self) -> str:
            return "Unserializable()"

    result = _safe_repr(Unserializable())
    assert isinstance(result, str)
    assert "Unserializable" in result


def test_surface_mitm_addon_errors_no_file(tmp_path):
    from qa_dashboard.pytest_plugin import _surface_mitm_addon_errors

    _surface_mitm_addon_errors(tmp_path)  # no _flows dir — should not raise


def test_surface_mitm_addon_errors_with_errors(tmp_path, caplog):
    from qa_dashboard.pytest_plugin import _surface_mitm_addon_errors

    err_log = tmp_path / "_flows" / "_addon_errors.log"
    err_log.parent.mkdir(parents=True)
    err_log.write_text("ERROR line 1\nERROR line 2\n", encoding="utf-8")

    import logging

    with caplog.at_level(logging.WARNING, logger="qa_dashboard"):
        _surface_mitm_addon_errors(tmp_path)  # should log a warning, not raise
    assert any("mitm addon" in r.message for r in caplog.records)


def test_surface_mitm_addon_errors_none_run_dir():
    from qa_dashboard.pytest_plugin import _surface_mitm_addon_errors

    _surface_mitm_addon_errors(None)  # should be a no-op
