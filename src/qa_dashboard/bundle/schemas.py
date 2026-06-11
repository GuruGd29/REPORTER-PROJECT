from __future__ import annotations

__all__ = [
    "BundleValidationError",
    "validate_console",
    "validate_flow",
    "validate_manifest",
    "validate_screenshot",
    "validate_step",
    "validate_test_record",
]


class BundleValidationError(ValueError):
    pass


_TEST_STATUSES = {"pass", "fail", "skip", "error", "xfailed", "xpassed"}
_STEP_STATUSES = {"pass", "fail", "skip"}
_SUBSTEP_STATUSES = {"pass", "fail"}
_LOG_LEVELS = {"DEBUG", "INFO", "WARN", "WARNING", "ERROR", "CRITICAL"}
_BODY_ENCODINGS = {"json", "text", "base64", "empty", "omitted"}


def _require(cond: bool, path: str, msg: str) -> None:
    if not cond:
        raise BundleValidationError(f"{path}: {msg}")


def _require_keys(obj: dict, keys: list[str], path: str) -> None:
    for k in keys:
        _require(k in obj, f"{path}.{k}", "missing required field")


def validate_substep(s: dict, path: str) -> None:
    _require(isinstance(s, dict), path, "must be an object")
    _require_keys(s, ["name", "status", "duration_ms"], path)
    _require(
        s["status"] in _SUBSTEP_STATUSES,
        f"{path}.status",
        f"expected one of {sorted(_SUBSTEP_STATUSES)}, got {s['status']!r}",
    )
    _require(isinstance(s["duration_ms"], int), f"{path}.duration_ms", "must be int")


def validate_step(s: dict, path: str) -> None:
    _require(isinstance(s, dict), path, "must be an object")
    _require_keys(s, ["id", "name", "status", "substeps", "screenshot_ids", "flow_ids"], path)
    _require(isinstance(s["id"], int) and s["id"] >= 1, f"{path}.id", "must be int >= 1")
    _require(
        s["status"] in _STEP_STATUSES,
        f"{path}.status",
        f"expected one of {sorted(_STEP_STATUSES)}, got {s['status']!r}",
    )
    _require(isinstance(s["substeps"], list), f"{path}.substeps", "must be array")
    for i, ss in enumerate(s["substeps"]):
        validate_substep(ss, f"{path}.substeps[{i}]")
    _require(isinstance(s["screenshot_ids"], list), f"{path}.screenshot_ids", "must be array")
    _require(isinstance(s["flow_ids"], list), f"{path}.flow_ids", "must be array")
    if s["status"] == "fail":
        _require(s.get("error") is not None, f"{path}.error", "must be non-null for failed step")
    if s["status"] == "skip":
        # skip_reason may be null but key present
        _require("skip_reason" in s, f"{path}.skip_reason", "missing")


def validate_flow(f: dict, path: str) -> None:
    _require(isinstance(f, dict), path, "must be an object")
    _require_keys(
        f,
        [
            "id",
            "timestamp",
            "method",
            "url",
            "host",
            "path",
            "status_code",
            "duration_ms",
            "step_id",
            "request",
            "response",
        ],
        path,
    )
    enc = f["request"].get("body_encoding")
    _require(
        enc in _BODY_ENCODINGS,
        f"{path}.request.body_encoding",
        f"expected one of {sorted(_BODY_ENCODINGS)}, got {enc!r}",
    )
    enc2 = f["response"].get("body_encoding")
    _require(
        enc2 in _BODY_ENCODINGS,
        f"{path}.response.body_encoding",
        f"expected one of {sorted(_BODY_ENCODINGS)}, got {enc2!r}",
    )


def validate_screenshot(s: dict, path: str) -> None:
    _require(isinstance(s, dict), path, "must be an object")
    _require_keys(
        s, ["id", "step_id", "captured_at", "filename", "asset_path", "size_bytes", "label"], path
    )


def validate_console(c: dict, path: str) -> None:
    _require(isinstance(c, dict), path, "must be an object")
    _require_keys(c, ["ts", "level", "logger", "message"], path)
    lvl = c["level"]
    if lvl == "WARNING":
        # accept WARNING as alias for WARN
        pass
    _require(
        lvl in _LOG_LEVELS, f"{path}.level", f"expected one of {sorted(_LOG_LEVELS)}, got {lvl!r}"
    )


def validate_test_record(record: dict) -> None:
    """Raise BundleValidationError if the record violates the schema."""
    _require(isinstance(record, dict), "record", "must be an object")
    _require_keys(
        record,
        [
            "schema_version",
            "test_id",
            "nodeid",
            "name",
            "file",
            "line",
            "status",
            "started_at",
            "ended_at",
            "duration_ms",
            "tags",
            "parameters",
            "outcome",
            "steps",
            "flows",
            "screenshots",
            "console",
            "device",
            "app",
        ],
        "record",
    )
    _require(
        record["schema_version"] == 1,
        "record.schema_version",
        f"this builder produces schema_version 1, got {record['schema_version']!r}",
    )
    _require(
        record["status"] in _TEST_STATUSES,
        "record.status",
        f"expected one of {sorted(_TEST_STATUSES)}, got {record['status']!r}",
    )
    out = record["outcome"]
    _require_keys(
        out,
        ["phase", "longrepr", "traceback_summary", "stdout_tail", "stderr_tail"],
        "record.outcome",
    )
    for i, s in enumerate(record["steps"]):
        validate_step(s, f"record.steps[{i}]")
    for i, f in enumerate(record["flows"]):
        validate_flow(f, f"record.flows[{i}]")
    for i, s in enumerate(record["screenshots"]):
        validate_screenshot(s, f"record.screenshots[{i}]")
    for i, c in enumerate(record["console"]):
        validate_console(c, f"record.console[{i}]")


def validate_manifest(manifest: dict) -> None:
    _require(isinstance(manifest, dict), "manifest", "must be an object")
    _require_keys(
        manifest,
        [
            "schema_version",
            "run_id",
            "started_at",
            "ended_at",
            "duration_ms",
            "status",
            "summary",
            "environment",
            "source",
            "config",
            "tests",
        ],
        "manifest",
    )
    _require(
        manifest["schema_version"] == 1,
        "manifest.schema_version",
        f"this builder produces schema_version 1, got {manifest['schema_version']!r}",
    )
    _require(
        manifest["status"] in {"pass", "fail", "error", "in_progress"},
        "manifest.status",
        f"unexpected status {manifest['status']!r}",
    )
    s = manifest["summary"]
    _require_keys(
        s,
        ["total", "passed", "failed", "skipped", "error", "xfailed", "xpassed", "pass_rate"],
        "manifest.summary",
    )
