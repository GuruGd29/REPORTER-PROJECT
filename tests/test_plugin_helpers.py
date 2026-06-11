"""Unit tests for small helpers in qa_dashboard.pytest_plugin."""

from __future__ import annotations

import logging

from qa_dashboard.pytest_plugin import (
    _bool,
    _env_or,
    _safe_repr,
    _surface_mitm_addon_errors,
)


def test_bool_handles_truthy_strings():
    assert _bool("true", False) is True
    assert _bool("YES", False) is True
    assert _bool("on", False) is True
    assert _bool("1", False) is True


def test_bool_handles_falsy_strings():
    assert _bool("false", True) is False
    assert _bool("no", True) is False
    assert _bool("off", True) is False
    assert _bool("0", True) is False


def test_bool_falls_back_to_default_on_none():
    assert _bool(None, True) is True
    assert _bool(None, False) is False


def test_bool_passes_through_python_bool():
    assert _bool(True, False) is True
    assert _bool(False, True) is False


def test_env_or_returns_env_value(monkeypatch):
    monkeypatch.setenv("QA_TEST_VAR", "from_env")
    assert _env_or("QA_TEST_VAR", "default") == "from_env"


def test_env_or_returns_default_when_unset(monkeypatch):
    monkeypatch.delenv("QA_TEST_VAR", raising=False)
    assert _env_or("QA_TEST_VAR", "default") == "default"


def test_safe_repr_returns_json_serializable_unchanged():
    assert _safe_repr({"k": "v"}) == {"k": "v"}
    assert _safe_repr([1, 2, 3]) == [1, 2, 3]
    assert _safe_repr(None) is None


def test_safe_repr_falls_back_to_repr_for_non_serializable():
    class Custom:
        def __repr__(self):
            return "<Custom>"

    assert _safe_repr(Custom()) == "<Custom>"


def test_surface_mitm_addon_errors_no_op_when_log_missing(tmp_path, caplog):
    run = tmp_path / "run"
    (run / "_flows").mkdir(parents=True)
    with caplog.at_level(logging.WARNING, logger="qa_dashboard"):
        _surface_mitm_addon_errors(run)
    assert caplog.records == []


def test_surface_mitm_addon_errors_no_op_when_log_empty(tmp_path, caplog):
    run = tmp_path / "run"
    flows = run / "_flows"
    flows.mkdir(parents=True)
    (flows / "_addon_errors.log").write_text("", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="qa_dashboard"):
        _surface_mitm_addon_errors(run)
    assert caplog.records == []


def test_surface_mitm_addon_errors_warns_when_log_nonempty(tmp_path, caplog):
    run = tmp_path / "run"
    flows = run / "_flows"
    flows.mkdir(parents=True)
    (flows / "_addon_errors.log").write_text(
        "Traceback line one\nLine two\n",
        encoding="utf-8",
    )
    with caplog.at_level(logging.WARNING, logger="qa_dashboard"):
        _surface_mitm_addon_errors(run)
    assert any("mitm addon reported" in r.message for r in caplog.records)


def test_surface_mitm_addon_errors_handles_none(caplog):
    with caplog.at_level(logging.WARNING, logger="qa_dashboard"):
        _surface_mitm_addon_errors(None)
    assert caplog.records == []
