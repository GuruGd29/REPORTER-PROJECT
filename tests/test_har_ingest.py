"""Unit tests for qa_dashboard.ingest.har."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from qa_dashboard._redact import Redactor
from qa_dashboard.bundle.schemas import validate_manifest, validate_test_record
from qa_dashboard.ingest.har import har_entries_to_flows, ingest_har


def _minimal_har_entry(
    *,
    url: str = "https://api.example.com/users",
    method: str = "GET",
    status: int = 200,
    body_text: str | None = '{"ok": true}',
    body_mime: str = "application/json",
    request_headers: list | None = None,
    response_headers: list | None = None,
    time_ms: int = 42,
) -> dict:
    return {
        "startedDateTime": "2026-05-27T10:00:00.000Z",
        "time": time_ms,
        "request": {
            "method": method,
            "url": url,
            "httpVersion": "HTTP/2",
            "headers": request_headers
            or [
                {"name": "Accept", "value": "application/json"},
            ],
            "queryString": [],
            "cookies": [],
            "headersSize": -1,
            "bodySize": 0,
        },
        "response": {
            "status": status,
            "statusText": "OK",
            "httpVersion": "HTTP/2",
            "headers": response_headers
            or [
                {"name": "content-type", "value": body_mime},
            ],
            "cookies": [],
            "content": (
                {"size": len(body_text), "mimeType": body_mime, "text": body_text}
                if body_text is not None
                else {"size": 0, "mimeType": ""}
            ),
            "redirectURL": "",
            "headersSize": -1,
            "bodySize": len(body_text) if body_text else 0,
        },
        "cache": {},
        "timings": {"send": 0, "wait": time_ms - 2, "receive": 2},
    }


def _wrap(entries: list[dict]) -> dict:
    return {
        "log": {
            "version": "1.2",
            "creator": {"name": "test", "version": "1.0"},
            "entries": entries,
        }
    }


def test_har_entries_to_flows_parses_basic_request():
    flows = har_entries_to_flows(
        _wrap([_minimal_har_entry()]),
        step_id=1,
        redactor=Redactor(),
    )
    assert len(flows) == 1
    f = flows[0]
    assert f["method"] == "GET"
    assert f["url"] == "https://api.example.com/users"
    assert f["host"] == "api.example.com"
    assert f["path"] == "/users"
    assert f["status_code"] == 200
    assert f["step_id"] == 1
    assert f["response"]["body"] == {"ok": True}
    assert f["response"]["body_encoding"] == "json"


def test_har_flow_ids_start_from_start_id():
    flows = har_entries_to_flows(
        _wrap([_minimal_har_entry(), _minimal_har_entry()]),
        start_id=10,
        redactor=Redactor(),
    )
    assert [f["id"] for f in flows] == [10, 11]


def test_har_handles_base64_body():
    raw = b"\x00\x01\x02binary"
    encoded = base64.b64encode(raw).decode("ascii")
    entry = _minimal_har_entry(body_text=None)
    entry["response"]["content"] = {
        "size": len(raw),
        "mimeType": "application/octet-stream",
        "text": encoded,
        "encoding": "base64",
    }
    flows = har_entries_to_flows(_wrap([entry]), redactor=Redactor())
    assert flows[0]["response"]["body_encoding"] == "base64"


def test_har_handles_text_body():
    entry = _minimal_har_entry(
        body_text="hello world",
        body_mime="text/plain",
    )
    flows = har_entries_to_flows(_wrap([entry]), redactor=Redactor())
    assert flows[0]["response"]["body_encoding"] == "text"
    assert flows[0]["response"]["body"] == "hello world"


def test_har_redaction_applies_to_headers_and_body():
    entry = _minimal_har_entry(
        request_headers=[
            {"name": "Authorization", "value": "Bearer secret"},
            {"name": "X-Trace-Id", "value": "t1"},
        ],
        body_text='{"password": "p", "user": "alice"}',
    )
    r = Redactor(("authorization", "password"))
    flows = har_entries_to_flows(_wrap([entry]), redactor=r)
    f = flows[0]
    assert f["request"]["headers"]["authorization"] == "***"
    assert f["request"]["headers"]["x-trace-id"] == "t1"
    assert f["response"]["body"]["password"] == "***"
    assert f["response"]["body"]["user"] == "alice"


def test_har_skips_entries_without_url():
    bad = _minimal_har_entry()
    bad["request"]["url"] = ""
    flows = har_entries_to_flows(_wrap([bad]), redactor=Redactor())
    assert flows == []


def test_har_falls_back_to_timings_sum_when_time_missing():
    entry = _minimal_har_entry(time_ms=0)
    flows = har_entries_to_flows(_wrap([entry]), redactor=Redactor())
    assert flows[0]["duration_ms"] >= 0


def test_ingest_har_creates_valid_run_dir(tmp_path: Path):
    har_path = tmp_path / "trace.har"
    har_path.write_text(
        json.dumps(_wrap([_minimal_har_entry(), _minimal_har_entry(status=404)])),
        encoding="utf-8",
    )
    run_dir = ingest_har([har_path], out_root=tmp_path / "out")
    assert (run_dir / "manifest.json").exists()
    records = list((run_dir / "tests").glob("*.json"))
    assert len(records) == 1

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    validate_manifest(manifest)

    record = json.loads(records[0].read_text(encoding="utf-8"))
    validate_test_record(record)
    assert len(record["flows"]) == 2
    assert record["status"] == "pass"
    assert "har" in record["tags"]


def test_ingest_har_raises_on_no_files(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        ingest_har([tmp_path / "missing.har"], out_root=tmp_path / "out")


def test_ingest_har_skips_unparseable_files(tmp_path: Path):
    bad = tmp_path / "broken.har"
    bad.write_text("{not json", encoding="utf-8")
    good = tmp_path / "ok.har"
    good.write_text(json.dumps(_wrap([_minimal_har_entry()])), encoding="utf-8")
    run_dir = ingest_har([bad, good], out_root=tmp_path / "out")
    records = list((run_dir / "tests").glob("*.json"))
    assert len(records) == 1
