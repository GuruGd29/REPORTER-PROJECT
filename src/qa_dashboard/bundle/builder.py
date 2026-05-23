from __future__ import annotations

import json
from collections import OrderedDict, defaultdict
from pathlib import Path

from .. import SCHEMA_VERSION


def _read_flows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _read_console(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Normalize WARNING -> WARN for consistency with the spec
            if obj.get("level") == "WARNING":
                obj["level"] = "WARN"
            out.append(obj)
    return out


def build_test_record(
    *,
    test_id: str,
    nodeid: str,
    name: str,
    file: str,
    line: int | None,
    status: str,
    started_at: str,
    ended_at: str,
    duration_ms: int,
    tags: list[str],
    parameters: dict | None,
    outcome: dict,
    step_data: dict,
    run_dir: Path,
    device: dict | None = None,
    app: dict | None = None,
) -> dict:
    """Assemble a TestRecord per DATA_CONTRACTS.md section 2."""
    flows = _read_flows(run_dir / "_flows" / f"{test_id}.jsonl")
    console = _read_console(run_dir / "_logs" / f"{test_id}.jsonl")

    flow_ids_by_step: dict[int, list[int]] = defaultdict(list)
    for f in flows:
        sid = f.get("step_id")
        if sid is not None:
            flow_ids_by_step[int(sid)].append(f["id"])

    steps = step_data.get("steps", [])
    for step in steps:
        step["flow_ids"] = list(flow_ids_by_step.get(step["id"], []))

    record = OrderedDict([
        ("schema_version", SCHEMA_VERSION),
        ("test_id", test_id),
        ("nodeid", nodeid),
        ("name", name),
        ("file", file),
        ("line", line),
        ("status", status),
        ("started_at", started_at),
        ("ended_at", ended_at),
        ("duration_ms", duration_ms),
        ("tags", list(tags or [])),
        ("parameters", parameters),
        ("outcome", outcome),
        ("steps", steps),
        ("flows", flows),
        ("screenshots", step_data.get("screenshots", [])),
        ("console", console),
        ("device", device),
        ("app", app),
    ])
    return record
