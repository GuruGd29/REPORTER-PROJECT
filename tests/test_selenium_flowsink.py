"""Unit tests for qa_dashboard.integrations.selenium.FlowSink."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from qa_dashboard._paths import make_run_dir
from qa_dashboard._redact import Redactor
from qa_dashboard.integrations.selenium import FlowSink, resolve_run_dir


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    _, d = make_run_dir(tmp_path)
    return d


def _set_current(run_dir: Path, test_id: str, step_id: int = 0) -> None:
    (run_dir / "current.txt").write_text(f"{test_id}\t{step_id}", encoding="utf-8")


def test_flowsink_writes_to_expected_file(run_dir: Path):
    _set_current(run_dir, "t001_abc", step_id=2)
    sink = FlowSink(run_dir=run_dir, redactor=Redactor())
    sink.record(
        method="GET",
        url="https://api.example.com/users",
        status_code=200,
        response_headers={"content-type": "application/json"},
        response_body=b'{"ok": true}',
        duration_ms=42,
    )
    sink.close()

    p = run_dir / "_flows" / "t001_abc.jsonl"
    assert p.exists()
    line = p.read_text(encoding="utf-8").splitlines()
    assert len(line) == 1
    rec = json.loads(line[0])
    assert rec["method"] == "GET"
    assert rec["status_code"] == 200
    assert rec["step_id"] == 2
    assert rec["response"]["body"] == {"ok": True}


def test_flowsink_skips_when_no_current_test(run_dir: Path):
    sink = FlowSink(run_dir=run_dir, redactor=Redactor())
    sink.record(
        method="GET",
        url="https://example.com/",
        status_code=200,
    )
    sink.close()
    # No file was created.
    assert not any((run_dir / "_flows").glob("*.jsonl"))


def test_flowsink_assigns_sequential_ids(run_dir: Path):
    _set_current(run_dir, "t002_x")
    sink = FlowSink(run_dir=run_dir, redactor=Redactor())
    for _ in range(3):
        sink.record(
            method="GET",
            url="https://example.com/",
            status_code=200,
        )
    sink.close()

    records = [
        json.loads(line)
        for line in (run_dir / "_flows" / "t002_x.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [r["id"] for r in records] == [0, 1, 2]


def test_flowsink_respects_host_filter(run_dir: Path):
    _set_current(run_dir, "t003_y")
    sink = FlowSink(
        run_dir=run_dir,
        host_filter="example.com",
        redactor=Redactor(),
    )
    sink.record(method="GET", url="https://example.com/", status_code=200)
    sink.record(method="GET", url="https://other.com/", status_code=200)
    sink.close()

    lines = (run_dir / "_flows" / "t003_y.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["host"] == "example.com"


def test_flowsink_applies_redaction(run_dir: Path):
    _set_current(run_dir, "t004_z")
    redactor = Redactor(("authorization", "password"))
    sink = FlowSink(run_dir=run_dir, redactor=redactor)
    sink.record(
        method="POST",
        url="https://api.example.com/login",
        status_code=200,
        request_headers={"Authorization": "Bearer secret"},
        request_body=b'{"username": "alice", "password": "p4ss"}',
        response_headers={"content-type": "application/json"},
        response_body=b'{"token": "abc", "expires": 3600}',
    )
    sink.close()

    rec = json.loads(
        (run_dir / "_flows" / "t004_z.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert rec["request"]["headers"]["authorization"] == "***"
    assert rec["request"]["body"]["password"] == "***"
    assert rec["request"]["body"]["username"] == "alice"


def test_flowsink_explicit_test_id_bypasses_current_file(run_dir: Path):
    sink = FlowSink(
        run_dir=run_dir,
        test_id="t999_explicit",
        redactor=Redactor(),
    )
    sink.record(method="GET", url="https://example.com/", status_code=200)
    sink.close()
    assert (run_dir / "_flows" / "t999_explicit.jsonl").exists()


def test_flowsink_raises_when_no_run_dir(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("QA_DASHBOARD_RUN_DIR", raising=False)
    monkeypatch.setenv("QA_DASHBOARD_DIR", str(tmp_path / "nowhere"))
    with pytest.raises(FileNotFoundError):
        FlowSink()


def test_resolve_run_dir_picks_most_recent(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("QA_DASHBOARD_RUN_DIR", raising=False)
    monkeypatch.setenv("QA_DASHBOARD_DIR", str(tmp_path))
    _, _older = make_run_dir(tmp_path)
    import time as _t

    _t.sleep(0.02)
    _, newer = make_run_dir(tmp_path)
    assert resolve_run_dir() == newer
