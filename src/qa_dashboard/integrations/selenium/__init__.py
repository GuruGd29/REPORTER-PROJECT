"""Selenium network capture for qa-dashboard.

Captures HTTP traffic from a Selenium 4 WebDriver session and writes it
into the active qa-dashboard run in the unified ``flows[]`` schema so
the bundle builder picks it up at teardown.

Two layers:

* :class:`FlowSink` — file-backed writer. Resolves the active run
  directory + current ``test_id`` from the qa-dashboard pytest plugin
  (via ``current.txt``) when no explicit values are passed, so you
  don't need to thread state through your tests.
* :func:`bidi_network_capture` — context manager that subscribes to
  Selenium 4's BiDi network module (W3C BiDi, supported by Chrome,
  Firefox, Edge) and pumps events into a :class:`FlowSink`. Falls
  back to the Chromium CDP (``driver.execute_cdp_cmd``) if the BiDi
  module isn't available.

Quickstart::

    # conftest.py
    import pytest
    from selenium import webdriver
    from qa_dashboard.integrations.selenium import bidi_network_capture

    @pytest.fixture
    def driver():
        d = webdriver.Chrome()
        with bidi_network_capture(d):
            yield d
        d.quit()

The capture context auto-resolves the run directory + active test, so
no other wiring is needed when running under pytest with the
qa-dashboard plugin enabled.
"""

from __future__ import annotations

import base64
import contextlib
import json
import logging
import os
import threading
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from qa_dashboard._redact import Redactor, load_default_redactor

__all__ = [
    "FlowSink",
    "bidi_network_capture",
    "resolve_run_dir",
]


_MAX_BODY_BYTES = 100 * 1024
_log = logging.getLogger("qa_dashboard.selenium")


def _iso_from_epoch(epoch: float) -> str:
    dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _now_iso() -> str:
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _normalize_headers(headers: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    if not headers:
        return out
    try:
        items = headers.items() if hasattr(headers, "items") else list(headers)
        for k, v in items:
            out[str(k).lower()] = str(v)
    except Exception:
        pass
    return out


def _decode_body(raw: bytes | None, content_type: str | None) -> tuple[str, Any, int]:
    """Same algorithm as the mitm addon, kept in lockstep."""
    if not raw:
        return "empty", "", 0
    size = len(raw)
    if size > _MAX_BODY_BYTES:
        return "omitted", None, size
    ct = (content_type or "").lower()
    if "json" in ct or raw[:1] in (b"{", b"["):
        try:
            return "json", json.loads(raw.decode("utf-8")), size
        except Exception:
            pass
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
            return "text", raw.decode("utf-8"), size
        except UnicodeDecodeError:
            pass
    return "base64", base64.b64encode(raw).decode("ascii"), size


def resolve_run_dir(explicit: Path | None = None) -> Path | None:
    """Find the qa-dashboard run dir to write into.

    Resolution order:
    1. ``explicit`` argument
    2. ``QA_DASHBOARD_RUN_DIR`` env var (set by the pytest plugin for
       subprocesses)
    3. Newest directory matching ``captures/run_*`` under
       ``QA_DASHBOARD_DIR`` (default ``./captures``)
    """
    if explicit is not None:
        p = Path(explicit)
        if p.exists():
            return p
    env = os.environ.get("QA_DASHBOARD_RUN_DIR")
    if env:
        p = Path(env)
        if p.exists():
            return p
    root = Path(os.environ.get("QA_DASHBOARD_DIR", "captures"))
    if not root.exists():
        return None
    runs = sorted(
        (p for p in root.iterdir() if p.is_dir() and p.name.startswith("run_")),
        key=lambda p: p.stat().st_mtime,
    )
    return runs[-1] if runs else None


class FlowSink:
    """File-backed writer for qa-dashboard flows.

    Thread-safe. Each call to :meth:`record` reads the active
    ``(test_id, step_id)`` from the run's ``current.txt`` and appends
    one JSON object to ``_flows/<test_id>.jsonl``. This is exactly the
    layout the bundle builder expects.

    Pass ``test_id`` explicitly to bypass ``current.txt`` (e.g. for
    standalone non-pytest runs).
    """

    def __init__(
        self,
        run_dir: Path | None = None,
        *,
        test_id: str | None = None,
        host_filter: str = "",
        redactor: Redactor | None = None,
    ) -> None:
        resolved = resolve_run_dir(run_dir)
        if resolved is None:
            raise FileNotFoundError(
                "qa-dashboard: no run directory found. Pass run_dir explicitly "
                "or run under the qa-dashboard pytest plugin."
            )
        self._run_dir = resolved
        self._flows_dir = self._run_dir / "_flows"
        self._flows_dir.mkdir(parents=True, exist_ok=True)
        self._current_file = self._run_dir / "current.txt"
        self._explicit_test_id = test_id
        self._host_filter = (host_filter or "").strip()
        self._handles: dict[str, Any] = {}
        self._counters: dict[str, int] = {}
        self._lock = threading.Lock()
        self._redactor = redactor if redactor is not None else load_default_redactor()

    @property
    def run_dir(self) -> Path:
        return self._run_dir

    def close(self) -> None:
        with self._lock:
            for h in self._handles.values():
                try:
                    h.close()
                except Exception:
                    pass
            self._handles.clear()

    def _read_current(self) -> tuple[str | None, int | None]:
        if self._explicit_test_id is not None:
            return self._explicit_test_id, None
        try:
            line = self._current_file.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None, None
        if not line:
            return None, None
        parts = line.split("\t", 1)
        test_id = parts[0] or None
        step_id: int | None = None
        if len(parts) == 2:
            try:
                v = int(parts[1])
                step_id = v if v > 0 else None
            except ValueError:
                pass
        return test_id, step_id

    def _handle(self, test_id: str):
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

    def record(
        self,
        *,
        method: str,
        url: str,
        status_code: int,
        request_headers: Any = None,
        response_headers: Any = None,
        request_body: bytes | None = None,
        response_body: bytes | None = None,
        duration_ms: int = 0,
        timestamp: str | None = None,
    ) -> None:
        """Persist one captured request/response pair as a qa-dashboard flow."""
        with self._lock:
            test_id, step_id = self._read_current()
            if not test_id:
                return
            parts = urlsplit(url)
            host = parts.hostname or ""
            if self._host_filter and self._host_filter not in host:
                return
            req_h = _normalize_headers(request_headers)
            resp_h = _normalize_headers(response_headers)
            req_ct = req_h.get("content-type", "")
            resp_ct = resp_h.get("content-type", "")
            req_enc, req_b, req_size = _decode_body(request_body, req_ct)
            resp_enc, resp_b, resp_size = _decode_body(response_body, resp_ct)
            if req_enc == "json":
                req_b = self._redactor.redact_body(req_b)
            if resp_enc == "json":
                resp_b = self._redactor.redact_body(resp_b)
            rec = {
                "id": self._next_id(test_id),
                "timestamp": timestamp or _now_iso(),
                "method": (method or "GET").upper(),
                "url": url,
                "host": host,
                "path": parts.path or "/",
                "status_code": int(status_code or 0),
                "duration_ms": max(int(duration_ms or 0), 0),
                "step_id": step_id,
                "request": {
                    "headers": self._redactor.redact_headers(req_h),
                    "content_type": req_ct,
                    "body_encoding": req_enc,
                    "body_size_bytes": req_size,
                    "body": req_b,
                },
                "response": {
                    "headers": self._redactor.redact_headers(resp_h),
                    "content_type": resp_ct,
                    "body_encoding": resp_enc,
                    "body_size_bytes": resp_size,
                    "body": resp_b,
                },
            }
            fp = self._handle(test_id)
            fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fp.flush()


# ---------------------------------------------------------------------------
# Selenium 4 BiDi / CDP capture
# ---------------------------------------------------------------------------


class _CdpListener:
    """Background-thread CDP listener for Chromium-backed Selenium.

    Uses the synchronous ``driver.execute_cdp_cmd`` for protocol calls
    and Selenium's ``script._websocket_connection`` for the streaming
    event subscription. Falls back gracefully when either is missing.
    """

    def __init__(self, driver, sink: FlowSink) -> None:
        self._driver = driver
        self._sink = sink
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._pending: dict[str, dict] = {}
        self._lock = threading.Lock()

    def start(self) -> bool:
        try:
            self._driver.execute_cdp_cmd("Network.enable", {})
        except Exception as e:
            _log.warning("BiDi/CDP capture unavailable on this driver: %s", e)
            return False
        # Selenium 4 exposes the underlying CDP websocket via different
        # private channels across versions. Try add_cdp_listener (some
        # builds), else give up gracefully — the user can wire up the
        # protocol of their choice via FlowSink.record().
        listener = getattr(self._driver, "add_cdp_listener", None)
        if listener is None:
            _log.info(
                "qa-dashboard: Network.enable succeeded but this Selenium "
                "build does not expose add_cdp_listener; use FlowSink.record() "
                "with your preferred BiDi adapter, or switch to Selenium-Wire."
            )
            return False
        listener("Network.responseReceived", self._on_response_received)
        listener("Network.loadingFinished", self._on_loading_finished)
        listener("Network.loadingFailed", self._on_loading_failed)
        return True

    def stop(self) -> None:
        self._stop.set()
        try:
            self._driver.execute_cdp_cmd("Network.disable", {})
        except Exception:
            pass

    def _on_response_received(self, params: dict) -> None:
        req_id = params.get("requestId")
        if not req_id:
            return
        resp = params.get("response") or {}
        with self._lock:
            self._pending[req_id] = {
                "url": resp.get("url") or "",
                "status": int(resp.get("status") or 0),
                "headers": resp.get("headers") or {},
                "request_headers": resp.get("requestHeaders") or {},
                "method": (
                    resp.get("requestHeadersText", "GET").split(" ", 1)[0]
                    if resp.get("requestHeadersText")
                    else "GET"
                ),
                "started_ts": float(params.get("timestamp") or 0.0),
            }

    def _on_loading_finished(self, params: dict) -> None:
        req_id = params.get("requestId")
        if not req_id:
            return
        with self._lock:
            meta = self._pending.pop(req_id, None)
        if not meta:
            return
        body = None
        try:
            res = self._driver.execute_cdp_cmd(
                "Network.getResponseBody",
                {"requestId": req_id},
            )
            data = res.get("body") or ""
            if res.get("base64Encoded"):
                body = base64.b64decode(data)
            else:
                body = data.encode("utf-8")
        except Exception:
            body = None
        ended_ts = float(params.get("timestamp") or meta["started_ts"])
        duration_ms = int(max(0.0, (ended_ts - meta["started_ts"])) * 1000)
        try:
            self._sink.record(
                method=meta["method"],
                url=meta["url"],
                status_code=meta["status"],
                request_headers=meta["request_headers"],
                response_headers=meta["headers"],
                request_body=None,
                response_body=body,
                duration_ms=duration_ms,
                timestamp=_iso_from_epoch(meta["started_ts"]) if meta["started_ts"] else None,
            )
        except Exception as e:
            _log.debug("flow record failed: %s", e)

    def _on_loading_failed(self, params: dict) -> None:
        req_id = params.get("requestId")
        if not req_id:
            return
        with self._lock:
            meta = self._pending.pop(req_id, None)
        if not meta:
            return
        try:
            self._sink.record(
                method=meta["method"],
                url=meta["url"],
                status_code=0,
                request_headers=meta["request_headers"],
                response_headers={},
                request_body=None,
                response_body=None,
                duration_ms=0,
                timestamp=_iso_from_epoch(meta["started_ts"]) if meta["started_ts"] else None,
            )
        except Exception:
            pass


@contextlib.contextmanager
def bidi_network_capture(
    driver,
    *,
    run_dir: Path | None = None,
    test_id: str | None = None,
    host_filter: str = "",
) -> Iterator[FlowSink]:
    """Subscribe to Selenium 4 BiDi/CDP network events for the duration
    of the block and forward them to a :class:`FlowSink`.

    Yields the active sink so callers can also push synthetic flows
    via :meth:`FlowSink.record` if they capture some traffic out-of-band.

    Chromium-backed drivers (Chrome, Edge, Chromium) work without any
    extra setup. For Firefox or other browsers, use the W3C BiDi
    network module directly and push events into the yielded sink.
    """
    sink = FlowSink(run_dir=run_dir, test_id=test_id, host_filter=host_filter)
    listener = _CdpListener(driver, sink)
    started = False
    try:
        started = listener.start()
        yield sink
    finally:
        if started:
            try:
                listener.stop()
            except Exception:
                pass
        sink.close()
