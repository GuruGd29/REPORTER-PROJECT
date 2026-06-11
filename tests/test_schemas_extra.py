"""Edge-case tests for qa_dashboard.bundle.schemas."""

from __future__ import annotations

import pytest

from qa_dashboard.bundle.schemas import (
    BundleValidationError,
    validate_console,
    validate_flow,
    validate_screenshot,
    validate_step,
    validate_substep,
)


def _minimal_step(**overrides) -> dict:
    base = {
        "id": 1,
        "name": "s",
        "status": "pass",
        "substeps": [],
        "screenshot_ids": [],
        "flow_ids": [],
    }
    base.update(overrides)
    return base


def test_validate_step_passes_minimal():
    validate_step(_minimal_step(), "step")


def test_validate_step_rejects_bad_status():
    with pytest.raises(BundleValidationError):
        validate_step(_minimal_step(status="banana"), "step")


def test_validate_step_requires_error_when_failed():
    with pytest.raises(BundleValidationError):
        validate_step(_minimal_step(status="fail", error=None), "step")


def test_validate_step_requires_skip_reason_key_when_skipped():
    s = _minimal_step(status="skip")
    with pytest.raises(BundleValidationError):
        validate_step(s, "step")
    s["skip_reason"] = None
    validate_step(s, "step")


def test_validate_substep_rejects_non_int_duration():
    with pytest.raises(BundleValidationError):
        validate_substep(
            {"name": "x", "status": "pass", "duration_ms": "100"},
            "substep",
        )


def test_validate_flow_rejects_bad_body_encoding():
    flow = {
        "id": 1,
        "timestamp": "x",
        "method": "GET",
        "url": "u",
        "host": "h",
        "path": "/p",
        "status_code": 200,
        "duration_ms": 0,
        "step_id": None,
        "request": {"body_encoding": "banana"},
        "response": {"body_encoding": "json"},
    }
    with pytest.raises(BundleValidationError):
        validate_flow(flow, "flow")


def test_validate_screenshot_requires_all_fields():
    with pytest.raises(BundleValidationError):
        validate_screenshot({"id": "x"}, "screenshot")


def test_validate_console_accepts_warning_as_warn_alias():
    validate_console(
        {"ts": "x", "level": "WARNING", "logger": "x", "message": "x"},
        "console",
    )


def test_validate_console_rejects_unknown_level():
    with pytest.raises(BundleValidationError):
        validate_console(
            {"ts": "x", "level": "NOPE", "logger": "x", "message": "x"},
            "console",
        )
