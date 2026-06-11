from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from pathlib import Path


def make_run_dir(base: Path) -> tuple[str, Path]:
    """Create a unique run directory. Returns (run_id, path)."""
    base = Path(base)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    suffix = secrets.token_hex(3)
    run_id = f"run_{ts}_{suffix}"
    path = base / run_id
    path.mkdir(parents=True, exist_ok=False)
    (path / "tests").mkdir()
    (path / "assets" / "screenshots").mkdir(parents=True)
    (path / "_flows").mkdir()
    (path / "_logs").mkdir()
    (path / "current.txt").write_text("", encoding="utf-8")
    return run_id, path


_NODEID_SANITIZE = re.compile(r"[^A-Za-z0-9_]")


def sanitize_nodeid(nodeid: str, max_len: int = 80) -> str:
    """Sanitize a pytest nodeid for use in a filename."""
    s = nodeid.replace("/", "_").replace("::", "_").replace("[", "_").replace("]", "_")
    s = _NODEID_SANITIZE.sub("_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:max_len]


def make_test_id(seq: int, nodeid: str) -> str:
    return f"t{seq:03d}_{sanitize_nodeid(nodeid)}"


def now_iso() -> str:
    return (
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.")
        + f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"
    )


def iso_from_epoch(epoch: float) -> str:
    dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def ms_between_iso(start: str, end: str) -> int:
    def parse(s: str) -> datetime:
        s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s)

    delta = parse(end) - parse(start)
    return int(delta.total_seconds() * 1000)
