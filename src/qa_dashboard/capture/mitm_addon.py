"""qa-dashboard mitmproxy addon (runs in mitmdump subprocess).

Reads ``current.txt`` on every flow to tag captured requests with the
active ``(test_id, step_id)``. Writes one JSON object per line to
``_flows/<test_id>.jsonl``. The parent pytest process reads these
files at teardown time.

This module must use only stdlib + mitmproxy + the dependency-free
``qa_dashboard._redact`` module. Do not import anything heavier from
``qa_dashboard.*`` here — the addon runs in a separate Python process.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

# Make the redaction helper importable when the addon is loaded by
# mitmdump from an installed wheel OR from a source checkout.
try:
    from qa_dashboard._redact import load_default_redactor
except ImportError:
    # Fallback: addon lives at src/qa_dashboard/capture/mitm_addon.py;
    # the package root is two levels up.
    _pkg_root = str(Path(__file__).resolve().parents[2])
    if _pkg_root not in sys.path:
        sys.path.insert(0, _pkg_root)
    from qa_dashboard._redact import load_default_redactor

from mitmproxy import http

MAX_BODY_BYTES = 100 * 1024  # 100 KB before being marked "omitted"


def _iso(epoch: float) -> str:
    dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _decode_body(content: bytes | None, content_type: str | None) -> tuple[str, Any, int]:
    """Return (encoding, body, size_bytes).

    encoding is one of: "json", "text", "base64", "empty", "omitted".
    """
    if not content:
        return "empty", "", 0
    size = len(content)
    if size > MAX_BODY_BYTES:
        return "omitted", None, size
    ct = (content_type or "").lower()
    # Try JSON first if it looks like JSON
    if "json" in ct or (content[:1] in (b"{", b"[")):
        try:
            text = content.decode("utf-8")
            parsed = json.loads(text)
            return "json", parsed, size
        except Exception:
            pass
    # Try text
    text_like = (
        "text" in ct
        or "xml" in ct
        or "html" in ct
        or "javascript" in ct
        or "form-urlencoded" in ct
        or ct == ""
    )
    if text_like:
        try:
            return "text", content.decode("utf-8"), size
        except UnicodeDecodeError:
            pass
    # Fallback: base64
    return "base64", base64.b64encode(content).decode("ascii"), size


def _headers_dict(headers) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for k, v in headers.items():
            out[str(k).lower()] = str(v)
    except (AttributeError, TypeError):
        # mitmproxy headers should always iterate; nothing to do but skip.
        pass
    return out


class QaDashboardAddon:
    def __init__(self) -> None:
        run_dir_s = os.environ.get("QA_DASHBOARD_RUN_DIR")
        if not run_dir_s:
            raise RuntimeError(
                "QA_DASHBOARD_RUN_DIR not set; addon should be spawned by qa-dashboard"
            )
        self._run_dir = Path(run_dir_s)
        self._flows_dir = self._run_dir / "_flows"
        self._flows_dir.mkdir(parents=True, exist_ok=True)
        self._current_file = self._run_dir / "current.txt"
        self._host_filter = (os.environ.get("QA_DASHBOARD_HOST_FILTER") or "").strip()
        self._handles: dict[str, Any] = {}
        # Sequential id per test_id, reset when test changes
        self._counters: dict[str, int] = {}
        # Redaction rules — env-var driven so the parent process can
        # pass through `QA_DASHBOARD_REDACT` without a custom protocol.
        self._redactor = load_default_redactor()

    # -- helpers -----------------------------------------------------

    def _read_current(self) -> tuple[str | None, int | None]:
        try:
            line = self._current_file.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None, None
        if not line:
            return None, None
        try:
            test_id, step_id_s = line.split("\t", 1)
        except ValueError:
            return None, None
        try:
            step_id = int(step_id_s)
        except ValueError:
            return None, None
        return test_id, (step_id if step_id > 0 else None)

    def _handle_for(self, test_id: str):
        h = self._handles.get(test_id)
        if h is None:
            path = self._flows_dir / f"{test_id}.jsonl"
            h = path.open("a", encoding="utf-8")
            self._handles[test_id] = h
        return h

    def _next_id(self, test_id: str) -> int:
        n = self._counters.get(test_id, 0)
        self._counters[test_id] = n + 1
        return n

    # -- mitmproxy hooks --------------------------------------------

    def response(self, flow: http.HTTPFlow) -> None:
        try:
            test_id, step_id = self._read_current()
            if not test_id:
                return
            host = flow.request.pretty_host or ""
            if self._host_filter and self._host_filter not in host:
                return
            parts = urlsplit(flow.request.url)
            req = flow.request
            resp = flow.response
            # Duration: prefer mitmproxy timestamps if available
            try:
                duration_ms = int((resp.timestamp_end - req.timestamp_start) * 1000)
            except Exception:
                duration_ms = 0
            req_enc, req_body, req_size = _decode_body(
                req.raw_content or b"",
                req.headers.get("content-type"),
            )
            resp_enc, resp_body, resp_size = _decode_body(
                resp.raw_content or b"",
                resp.headers.get("content-type"),
            )
            if req_enc == "json":
                req_body = self._redactor.redact_body(req_body)
            if resp_enc == "json":
                resp_body = self._redactor.redact_body(resp_body)
            record = {
                "id": self._next_id(test_id),
                "timestamp": _iso(req.timestamp_start),
                "method": req.method,
                "url": flow.request.url,
                "host": host,
                "path": parts.path or "/",
                "status_code": resp.status_code,
                "duration_ms": duration_ms,
                "step_id": step_id,
                "request": {
                    "headers": self._redactor.redact_headers(_headers_dict(req.headers)),
                    "content_type": req.headers.get("content-type", ""),
                    "body_encoding": req_enc,
                    "body_size_bytes": req_size,
                    "body": req_body,
                },
                "response": {
                    "headers": self._redactor.redact_headers(_headers_dict(resp.headers)),
                    "content_type": resp.headers.get("content-type", ""),
                    "body_encoding": resp_enc,
                    "body_size_bytes": resp_size,
                    "body": resp_body,
                },
            }
            fp = self._handle_for(test_id)
            fp.write(json.dumps(record, ensure_ascii=False) + "\n")
            fp.flush()
        except Exception:
            # Addon must never crash mitmdump; swallow.
            try:
                err = self._run_dir / "_flows" / "_addon_errors.log"
                with err.open("a", encoding="utf-8") as f:
                    import traceback as _tb

                    f.write(_tb.format_exc() + "\n")
            except Exception:
                pass

    def done(self) -> None:
        for h in self._handles.values():
            try:
                h.close()
            except Exception:
                pass
        self._handles.clear()


addons = [QaDashboardAddon()]
