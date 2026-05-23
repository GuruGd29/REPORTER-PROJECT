from __future__ import annotations

import json
import platform
import subprocess
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any

from . import SCHEMA_VERSION, __version__
from ._paths import now_iso


def _try(cmd: list[str]) -> str | None:
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True, timeout=2)
        return out.strip() or None
    except Exception:
        return None


def collect_environment() -> dict:
    try:
        import pytest as _pytest

        pytest_ver: str | None = _pytest.__version__
    except Exception:
        pytest_ver = None
    try:
        import mitmproxy as _mp

        mitm_ver: str | None = getattr(_mp, "__version__", None)
    except Exception:
        mitm_ver = None
    import getpass
    import socket

    try:
        host = socket.gethostname()
    except Exception:
        host = None
    try:
        user = getpass.getuser()
    except Exception:
        user = None
    return OrderedDict([
        ("pytest", pytest_ver),
        ("python", sys.version.split()[0]),
        ("platform", platform.platform()),
        ("mitmproxy", mitm_ver),
        ("qa_dashboard", __version__),
        ("hostname", host),
        ("user", user),
        ("cwd", str(Path.cwd())),
    ])


def collect_source() -> dict:
    """Best-effort git/source info; nulls allowed."""
    import os

    branch = _try(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    commit = _try(["git", "rev-parse", "--short", "HEAD"])
    commit_msg = _try(["git", "log", "-1", "--pretty=%s"])
    # Repo name = top-level dir name
    top = _try(["git", "rev-parse", "--show-toplevel"])
    repo = Path(top).name if top else None
    trigger = os.environ.get("QA_DASHBOARD_TRIGGER")
    if not trigger:
        if os.environ.get("CI"):
            trigger = "ci"
        else:
            trigger = "local"
    return OrderedDict([
        ("repo", repo),
        ("branch", branch),
        ("commit", commit),
        ("commit_message", commit_msg),
        ("trigger", trigger),
    ])


class ManifestWriter:
    """Maintains manifest.json across the run, flushing after each test."""

    def __init__(self, run_dir: Path, run_id: str, config: dict, pretty: bool = True) -> None:
        self._path = Path(run_dir) / "manifest.json"
        self._pretty = pretty
        self._data: dict[str, Any] = OrderedDict([
            ("schema_version", SCHEMA_VERSION),
            ("run_id", run_id),
            ("started_at", now_iso()),
            ("ended_at", None),
            ("duration_ms", None),
            ("status", "in_progress"),
            ("summary", OrderedDict([
                ("total", 0),
                ("passed", 0),
                ("failed", 0),
                ("skipped", 0),
                ("error", 0),
                ("xfailed", 0),
                ("xpassed", 0),
                ("pass_rate", 0.0),
            ])),
            ("environment", collect_environment()),
            ("source", collect_source()),
            ("config", config),
            ("tests", []),
        ])

    def started_at(self) -> str:
        return self._data["started_at"]

    def flush(self) -> None:
        text = json.dumps(self._data, ensure_ascii=False, indent=2 if self._pretty else None)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        import os
        os.replace(tmp, self._path)

    def add_test_summary(self, summary: dict) -> None:
        self._data["tests"].append(summary)
        self._recompute_summary()
        self.flush()

    def _recompute_summary(self) -> None:
        s = self._data["summary"]
        s["total"] = len(self._data["tests"])
        s["passed"] = sum(1 for t in self._data["tests"] if t["status"] == "pass")
        s["failed"] = sum(1 for t in self._data["tests"] if t["status"] == "fail")
        s["skipped"] = sum(1 for t in self._data["tests"] if t["status"] == "skip")
        s["error"] = sum(1 for t in self._data["tests"] if t["status"] == "error")
        s["xfailed"] = sum(1 for t in self._data["tests"] if t["status"] == "xfailed")
        s["xpassed"] = sum(1 for t in self._data["tests"] if t["status"] == "xpassed")
        s["pass_rate"] = round(s["passed"] / s["total"], 3) if s["total"] else 0.0

    def finalize(self) -> None:
        end = now_iso()
        from ._paths import ms_between_iso
        self._data["ended_at"] = end
        self._data["duration_ms"] = ms_between_iso(self._data["started_at"], end)
        s = self._data["summary"]
        if s["error"] > 0:
            self._data["status"] = "error"
        elif s["failed"] > 0:
            self._data["status"] = "fail"
        else:
            self._data["status"] = "pass"
        self.flush()
