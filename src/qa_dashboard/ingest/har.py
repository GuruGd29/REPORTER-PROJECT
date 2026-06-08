"""HAR (HTTP Archive) ingestor.

Reads HAR 1.2 files produced by browser DevTools, Playwright (via
``recordHar``), BrowserMob Proxy, mitmproxy ``--set hardump=...``, k6,
JMeter, Postman, Insomnia, and any other tool that emits the W3C HAR
format.

Two entry points:

* :func:`ingest_har` — create a brand-new run directory from one or
  more HAR files. Each HAR becomes a synthetic test entry; entries
  within a HAR become flows on that test.
* :func:`har_entries_to_flows` — parse a HAR file into the
  ``flows[]`` schema and return the list, so callers can attach those
  flows to an existing test record (used by the Playwright reporter
  fallback path and by the Selenium 4 BiDi adapter).

This module has zero non-stdlib imports.
"""
from __future__ import annotations

import base64
import binascii
import json
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .. import SCHEMA_VERSION
from .._manifest import collect_environment, collect_source
from .._paths import make_run_dir, sanitize_nodeid


_MAX_BODY_BYTES = 100 * 1024  # mirror mitm_addon.MAX_BODY_BYTES


def _iso_from_har_timestamp(s: str | None) -> str | None:
    if not s:
        return None
    s = s.strip()
    try:
        # HAR uses ISO 8601 with optional fractional seconds and timezone.
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    except (ValueError, TypeError):
        return None


def _now_iso() -> str:
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _headers_dict(headers: list[dict] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for h in headers or []:
        try:
            out[str(h.get("name", "")).lower()] = str(h.get("value", ""))
        except Exception:
            continue
    return out


def _decode_har_content(
    content: dict | None,
    headers_ct: str,
) -> tuple[str, Any, int]:
    """Return (encoding, body, size_bytes) using the same schema as mitm_addon."""
    if not content:
        return "empty", "", 0
    size = int(content.get("size") or 0)
    text = content.get("text")
    encoding = (content.get("encoding") or "").lower()
    ct = (content.get("mimeType") or headers_ct or "").lower()

    if text is None or text == "":
        # HAR allows omitting text for binary or stripped bodies
        if size > 0:
            return "omitted", None, size
        return "empty", "", 0

    if encoding == "base64":
        try:
            raw = base64.b64decode(text, validate=True)
        except (binascii.Error, ValueError):
            return "base64", text, size or len(text)
        if len(raw) > _MAX_BODY_BYTES:
            return "omitted", None, len(raw)
        if "json" in ct or (raw[:1] in (b"{", b"[")):
            try:
                return "json", json.loads(raw.decode("utf-8")), len(raw)
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass
        text_like = (
            "text" in ct or "xml" in ct or "html" in ct or "javascript" in ct
            or "form-urlencoded" in ct or ct == ""
        )
        if text_like:
            try:
                return "text", raw.decode("utf-8"), len(raw)
            except UnicodeDecodeError:
                pass
        return "base64", base64.b64encode(raw).decode("ascii"), len(raw)

    # plain text body
    body_bytes = text.encode("utf-8", errors="replace")
    if len(body_bytes) > _MAX_BODY_BYTES:
        return "omitted", None, len(body_bytes)
    if "json" in ct or text[:1] in ("{", "["):
        try:
            return "json", json.loads(text), len(body_bytes)
        except (json.JSONDecodeError, ValueError):
            pass
    return "text", text, len(body_bytes)


def _entry_to_flow(entry: dict, flow_id: int, step_id: int | None) -> dict | None:
    request = entry.get("request") or {}
    response = entry.get("response") or {}
    url = request.get("url") or ""
    method = (request.get("method") or "GET").upper()
    if not url:
        return None
    parts = urlsplit(url)
    host = parts.hostname or ""
    path = parts.path or "/"

    started = _iso_from_har_timestamp(entry.get("startedDateTime")) or _now_iso()
    # HAR `time` is total round-trip in milliseconds; fall back to summing
    # the timings block if missing.
    duration_ms = int(entry.get("time") or 0)
    if not duration_ms:
        t = entry.get("timings") or {}
        duration_ms = sum(
            int(t.get(k) or 0) for k in
            ("blocked", "dns", "connect", "send", "wait", "receive", "ssl")
            if (t.get(k) or 0) >= 0
        )

    req_headers = _headers_dict(request.get("headers"))
    resp_headers = _headers_dict(response.get("headers"))
    req_ct = req_headers.get("content-type", "")
    resp_ct = resp_headers.get("content-type", "")

    # HAR represents the request body under "postData", not "content"
    post = request.get("postData") or {}
    req_text = post.get("text")
    req_content = (
        {"text": req_text,
         "size": len(req_text.encode("utf-8")) if req_text else 0,
         "mimeType": post.get("mimeType") or req_ct,
         "encoding": ""}
        if req_text is not None else None
    )
    req_enc, req_body, req_size = _decode_har_content(req_content, req_ct)

    resp_enc, resp_body, resp_size = _decode_har_content(
        response.get("content"), resp_ct,
    )

    return OrderedDict([
        ("id", flow_id),
        ("timestamp", started),
        ("method", method),
        ("url", url),
        ("host", host),
        ("path", path),
        ("status_code", int(response.get("status") or 0)),
        ("duration_ms", max(duration_ms, 0)),
        ("step_id", step_id),
        ("request", OrderedDict([
            ("headers", req_headers),
            ("content_type", req_ct),
            ("body_encoding", req_enc),
            ("body_size_bytes", req_size),
            ("body", req_body),
        ])),
        ("response", OrderedDict([
            ("headers", resp_headers),
            ("content_type", resp_ct),
            ("body_encoding", resp_enc),
            ("body_size_bytes", resp_size),
            ("body", resp_body),
        ])),
    ])


def har_entries_to_flows(
    har: dict | str | Path,
    *,
    step_id: int | None = None,
    start_id: int = 0,
) -> list[dict]:
    """Convert a parsed HAR (or a path to one) into qa-dashboard flows.

    ``step_id`` is stamped on every flow so consumers can attach the
    captured network to a particular pseudo-step in the test record.
    ``start_id`` lets callers append to an existing flow list without
    colliding on the per-test ``id`` counter.
    """
    if isinstance(har, (str, Path)):
        har_data = json.loads(Path(har).read_text(encoding="utf-8"))
    else:
        har_data = har
    log = (har_data or {}).get("log") or {}
    entries = log.get("entries") or []
    out: list[dict] = []
    next_id = start_id
    for entry in entries:
        flow = _entry_to_flow(entry, next_id, step_id)
        if flow is None:
            continue
        out.append(flow)
        next_id += 1
    return out


def _collect_har_files(inputs: list[Path] | Path) -> list[Path]:
    if isinstance(inputs, (str, Path)):
        inputs = [Path(inputs)]
    files: list[Path] = []
    for inp in inputs:
        inp = Path(inp)
        if inp.is_dir():
            files.extend(sorted(p for p in inp.rglob("*.har")))
        elif inp.is_file():
            files.append(inp)
    return files


def ingest_har(
    inputs: list[Path] | Path,
    out_root: Path,
    repo_label: str | None = None,
) -> Path:
    """Ingest one or more HAR files into a new run directory.

    Each HAR file becomes one synthetic "test" entry whose ``flows[]``
    is the request/response trace. The status is always ``pass`` —
    HAR does not carry assertion outcomes. Pair with
    ``qa-dashboard ingest`` (JUnit XML) for tests + matching HAR for
    network in the same dashboard via separate runs.
    """
    har_files = _collect_har_files(inputs)
    if not har_files:
        raise FileNotFoundError(f"No .har files found in {inputs}")

    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    run_id, run_dir = make_run_dir(out_root)

    test_records: list[dict] = []
    test_summaries: list[dict] = []
    earliest_ts: str | None = None
    latest_ts: str | None = None
    total_ms = 0
    seq = 0

    for har_path in har_files:
        try:
            har_data = json.loads(har_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        seq += 1
        nodeid = f"har::{har_path.name}"
        test_id = f"t{seq:03d}_{sanitize_nodeid(nodeid)}"
        flows = har_entries_to_flows(har_data, step_id=1, start_id=0)
        if flows:
            started_at = flows[0]["timestamp"]
            ended_at = flows[-1]["timestamp"]
        else:
            started_at = _now_iso()
            ended_at = started_at
        duration_ms = sum(f["duration_ms"] for f in flows)

        outcome = OrderedDict([
            ("phase", "call"),
            ("longrepr", None),
            ("traceback_summary", None),
            ("stdout_tail", ""),
            ("stderr_tail", ""),
        ])
        steps = [OrderedDict([
            ("id", 1),
            ("name", "HAR replay"),
            ("status", "pass"),
            ("started_at", started_at),
            ("ended_at", ended_at),
            ("duration_ms", duration_ms),
            ("substeps", []),
            ("screenshot_ids", []),
            ("flow_ids", [f["id"] for f in flows]),
            ("error", None),
            ("skip_reason", None),
        ])]

        record = OrderedDict([
            ("schema_version", SCHEMA_VERSION),
            ("test_id", test_id),
            ("nodeid", nodeid),
            ("name", har_path.stem),
            ("file", str(har_path)),
            ("line", None),
            ("status", "pass"),
            ("started_at", started_at),
            ("ended_at", ended_at),
            ("duration_ms", duration_ms),
            ("tags", ["har"]),
            ("parameters", None),
            ("outcome", outcome),
            ("steps", steps),
            ("flows", flows),
            ("screenshots", []),
            ("console", []),
            ("device", None),
            ("app", None),
        ])
        test_records.append(record)
        test_summaries.append(OrderedDict([
            ("test_id", test_id),
            ("nodeid", nodeid),
            ("name", har_path.stem),
            ("file", str(har_path)),
            ("status", "pass"),
            ("started_at", started_at),
            ("duration_ms", duration_ms),
            ("step_count", 1),
            ("flow_count", len(flows)),
            ("screenshot_count", 0),
            ("tags", ["har"]),
            ("error_summary", None),
        ]))

        if earliest_ts is None or started_at < earliest_ts:
            earliest_ts = started_at
        if latest_ts is None or ended_at > latest_ts:
            latest_ts = ended_at
        total_ms += duration_ms

    for record in test_records:
        (run_dir / "tests" / f"{record['test_id']}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "total": len(test_summaries),
        "passed": len(test_summaries),
        "failed": 0,
        "skipped": 0,
        "error": 0,
        "xfailed": 0,
        "xpassed": 0,
    }
    summary["pass_rate"] = 1.0 if summary["total"] else 0.0

    env = collect_environment()
    env["pytest"] = None
    src = collect_source()
    if repo_label:
        src["repo"] = repo_label

    manifest = OrderedDict([
        ("schema_version", SCHEMA_VERSION),
        ("run_id", run_id),
        ("started_at", earliest_ts or _now_iso()),
        ("ended_at", latest_ts or _now_iso()),
        ("duration_ms", total_ms),
        ("status", "pass"),
        ("summary", summary),
        ("environment", env),
        ("source", src),
        ("config", {"ingestor": "har",
                    "inputs": [str(p) for p in har_files],
                    "command_line": ""}),
        ("tests", test_summaries),
    ])
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return run_dir
