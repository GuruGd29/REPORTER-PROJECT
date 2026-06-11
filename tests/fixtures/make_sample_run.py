"""Generate a fake qa-dashboard run directory for development.

Usage::

    python -m tests.fixtures.make_sample_run --tests 30 --fail-rate 0.15 \\
        --out captures/

Produces a fully-valid run directory with manifest, per-test records,
flows, screenshots, and console logs.
"""

from __future__ import annotations

import argparse
import json
import random
import struct
import zlib
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from qa_dashboard import SCHEMA_VERSION
from qa_dashboard._manifest import collect_environment, collect_source
from qa_dashboard._paths import sanitize_nodeid
from qa_dashboard.bundle.schemas import validate_manifest, validate_test_record
from qa_dashboard.report.generator import generate_index_html

# --- tiny PNG generator (no Pillow) ---------------------------------


def make_png(width: int = 320, height: int = 240, color: tuple = (200, 50, 50)) -> bytes:
    def chunk(name: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(name + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", crc)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b""
    for _ in range(height):
        raw += b"\x00" + bytes(color) * width
    idat = zlib.compress(raw)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


# --- sample data --------------------------------------------------------

NODEIDS = [
    "tests/api/test_auth.py::test_signin_smoke",
    "tests/api/test_auth.py::test_signin_invalid_password",
    "tests/api/test_payment.py::test_refund_eligible_user",
    "tests/api/test_payment.py::test_refund_ineligible_user",
    "tests/ui/test_home.py::test_carousel_renders",
    "tests/ui/test_home.py::test_search_returns_results",
    "tests/ui/test_player.py::test_playback_starts",
    "tests/ui/test_player.py::test_subtitle_toggle",
    "tests/ui/test_player.py::test_quality_switcher",
    "tests/ui/test_profile.py::test_switch_profile",
    "tests/ui/test_profile.py::test_sign_out",
    "tests/api/test_search.py::test_query_basic",
    "tests/api/test_search.py::test_query_unicode",
    "tests/api/test_search.py::test_query_empty",
    "tests/api/test_recommendations.py::test_for_new_user",
    "tests/api/test_recommendations.py::test_for_returning_user",
    "tests/integration/test_subscription.py::test_upgrade_flow",
    "tests/integration/test_subscription.py::test_downgrade_flow",
    "tests/integration/test_subscription.py::test_cancel_flow",
    "tests/integration/test_offline.py::test_download_episode",
]

STEP_NAMES = [
    "Launch app",
    "Tap Sign In",
    "Enter credentials",
    "Verify home screen",
    "Browse carousel",
    "Open details page",
    "Start playback",
    "Toggle subtitles",
    "Open profile menu",
    "Sign out",
    "Tear down session",
]


def make_sample(
    out_root: Path, num_tests: int, fail_rate: float, steps_per_test: int, seed: int | None = None
) -> Path:
    rng = random.Random(seed)
    start = datetime(2026, 5, 22, 12, 34, 56, tzinfo=timezone.utc)
    ts = start.strftime("%Y%m%d_%H%M%S")
    suffix = f"sample{seed if seed is not None else rng.randint(0, 0xFFFFFF):06x}"[:8]
    run_id = f"run_{ts}_{suffix}"
    run_dir = out_root / run_id
    (run_dir / "tests").mkdir(parents=True)
    (run_dir / "assets" / "screenshots").mkdir(parents=True)

    nodeids = (NODEIDS * ((num_tests // len(NODEIDS)) + 1))[:num_tests]
    rng.shuffle(nodeids)

    cursor = start
    test_summaries = []
    for i, nodeid in enumerate(nodeids, start=1):
        test_id = f"t{i:03d}_{sanitize_nodeid(nodeid)}"
        is_fail = rng.random() < fail_rate
        is_skip = (not is_fail) and rng.random() < 0.05
        status = "fail" if is_fail else ("skip" if is_skip else "pass")
        nsteps = max(1, int(rng.gauss(steps_per_test, 2)))
        # Build steps
        steps = []
        screenshots = []
        cur = cursor
        fail_step_idx = rng.randint(0, max(0, nsteps - 1)) if is_fail else -1
        for j in range(nsteps):
            sname = STEP_NAMES[j % len(STEP_NAMES)] + (f" #{j + 1}" if j >= len(STEP_NAMES) else "")
            dur_ms = rng.randint(60, 1400)
            st_start = cur
            st_end = cur + timedelta(milliseconds=dur_ms)
            sstatus = "fail" if j == fail_step_idx else ("pass" if not is_skip else "skip")
            step = OrderedDict(
                [
                    ("id", j + 1),
                    ("name", sname),
                    ("status", sstatus),
                    ("started_at", _iso(st_start)),
                    ("ended_at", _iso(st_end)),
                    ("duration_ms", dur_ms),
                    (
                        "substeps",
                        [
                            {
                                "name": "Locate",
                                "status": "pass",
                                "duration_ms": rng.randint(20, 80),
                            },
                            {
                                "name": "Act",
                                "status": "fail" if sstatus == "fail" else "pass",
                                "duration_ms": rng.randint(40, 200),
                            },
                        ],
                    ),
                    ("screenshot_ids", []),
                    ("flow_ids", []),
                    (
                        "error",
                        None
                        if sstatus != "fail"
                        else {
                            "type": "AssertionError",
                            "message": "expected element to be visible",
                            "traceback": "Traceback (most recent call last):\n  ...\nAssertionError",
                        },
                    ),
                    (
                        "skip_reason",
                        "after previous failure" if sstatus == "skip" and is_skip else None,
                    ),
                ]
            )
            # 0-3 screenshots per step
            for k in range(rng.randint(0, 3)):
                shot_id = f"{test_id}_step_{step['id']}_{k + 1:03d}"
                fname = f"{shot_id}.png"
                color = (
                    255 if sstatus == "fail" else 30,
                    50 if sstatus == "fail" else 158,
                    50 if sstatus == "fail" else 117,
                )
                (run_dir / "assets" / "screenshots" / fname).write_bytes(make_png(240, 360, color))
                rec = OrderedDict(
                    [
                        ("id", shot_id),
                        ("step_id", step["id"]),
                        (
                            "captured_at",
                            _iso(st_start + timedelta(milliseconds=rng.randint(10, dur_ms))),
                        ),
                        ("filename", fname),
                        ("asset_path", f"assets/screenshots/{fname}"),
                        ("width", 240),
                        ("height", 360),
                        ("size_bytes", len(make_png(240, 360, color))),
                        ("label", f"step {step['id']} shot {k + 1}"),
                    ]
                )
                screenshots.append(rec)
                step["screenshot_ids"].append(shot_id)
            steps.append(step)
            cur = st_end

        # Flows
        flows = []
        for fi in range(rng.randint(0, 20)):
            sidx = rng.randint(0, nsteps - 1)
            step_id = steps[sidx]["id"]
            tstart = steps[sidx]["started_at"]
            method = rng.choice(["GET", "POST", "PUT", "DELETE"])
            code = rng.choices(
                [200, 200, 200, 304, 400, 404, 429, 500], weights=[5, 5, 5, 1, 1, 1, 1, 1]
            )[0]
            f = OrderedDict(
                [
                    ("id", fi),
                    ("timestamp", tstart),
                    ("method", method),
                    ("url", f"https://api.example.com/v1/resource/{fi}"),
                    ("host", "api.example.com"),
                    ("path", f"/v1/resource/{fi}"),
                    ("status_code", code),
                    ("duration_ms", rng.randint(40, 1200)),
                    ("step_id", step_id),
                    (
                        "request",
                        {
                            "headers": {"accept": "application/json"},
                            "content_type": "application/json",
                            "body_encoding": "empty",
                            "body_size_bytes": 0,
                            "body": "",
                        },
                    ),
                    (
                        "response",
                        {
                            "headers": {"content-type": "application/json"},
                            "content_type": "application/json",
                            "body_encoding": "json",
                            "body_size_bytes": 42,
                            "body": {"id": fi, "ok": code < 400},
                        },
                    ),
                ]
            )
            flows.append(f)
            steps[sidx]["flow_ids"].append(fi)

        # Console
        console = [
            {
                "ts": _iso(cursor + timedelta(milliseconds=10)),
                "level": "INFO",
                "logger": "test",
                "message": f"Starting {nodeid}",
            },
            {
                "ts": _iso(cur),
                "level": "INFO" if not is_fail else "ERROR",
                "logger": "test",
                "message": ("FAILED" if is_fail else "PASSED") + f" {nodeid}",
            },
        ]
        if is_fail:
            console.append(
                {
                    "ts": _iso(cur + timedelta(milliseconds=5)),
                    "level": "WARN",
                    "logger": "retry",
                    "message": "exhausted 3 retries",
                }
            )

        outcome = OrderedDict(
            [
                ("phase", "call"),
                ("longrepr", "AssertionError: failure simulated" if is_fail else None),
                ("traceback_summary", "AssertionError at line 42" if is_fail else None),
                ("stdout_tail", ""),
                ("stderr_tail", ""),
            ]
        )
        duration_ms = int((cur - cursor).total_seconds() * 1000)
        rec = OrderedDict(
            [
                ("schema_version", SCHEMA_VERSION),
                ("test_id", test_id),
                ("nodeid", nodeid),
                ("name", nodeid.split("::")[-1]),
                ("file", nodeid.split("::")[0]),
                ("line", rng.randint(10, 200)),
                ("status", status),
                ("started_at", _iso(cursor)),
                ("ended_at", _iso(cur)),
                ("duration_ms", duration_ms),
                (
                    "tags",
                    rng.sample(["smoke", "regression", "ui", "api", "slow"], k=rng.randint(0, 2)),
                ),
                ("parameters", None),
                ("outcome", outcome),
                ("steps", steps),
                ("flows", flows),
                ("screenshots", screenshots),
                ("console", console),
                (
                    "device",
                    {
                        "platform": "Android",
                        "platform_version": "14",
                        "model": "Pixel 7 emulator",
                        "locale": "en_IN",
                    },
                ),
                ("app", {"package": "in.startv.hotstar", "version": "24.05.15.3"}),
            ]
        )
        validate_test_record(rec)
        (run_dir / "tests" / f"{test_id}.json").write_text(
            json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        test_summaries.append(
            OrderedDict(
                [
                    ("test_id", test_id),
                    ("nodeid", nodeid),
                    ("name", rec["name"]),
                    ("file", rec["file"]),
                    ("status", status),
                    ("started_at", rec["started_at"]),
                    ("duration_ms", duration_ms),
                    ("step_count", len(steps)),
                    ("flow_count", len(flows)),
                    ("screenshot_count", len(screenshots)),
                    ("tags", rec["tags"]),
                    ("error_summary", "AssertionError: failure simulated" if is_fail else None),
                ]
            )
        )
        cursor = cur + timedelta(milliseconds=rng.randint(50, 300))

    s = {
        "total": num_tests,
        "passed": sum(1 for t in test_summaries if t["status"] == "pass"),
        "failed": sum(1 for t in test_summaries if t["status"] == "fail"),
        "skipped": sum(1 for t in test_summaries if t["status"] == "skip"),
        "error": 0,
        "xfailed": 0,
        "xpassed": 0,
    }
    s["pass_rate"] = round(s["passed"] / max(s["total"], 1), 3)
    manifest = OrderedDict(
        [
            ("schema_version", SCHEMA_VERSION),
            ("run_id", run_id),
            ("started_at", _iso(start)),
            ("ended_at", _iso(cursor)),
            ("duration_ms", int((cursor - start).total_seconds() * 1000)),
            ("status", "fail" if s["failed"] else "pass"),
            ("summary", s),
            ("environment", collect_environment()),
            ("source", collect_source()),
            (
                "config",
                {
                    "mitm_port": 8080,
                    "host_filter": "",
                    "screenshot_on_fail": True,
                    "command_line": "sample",
                },
            ),
            ("tests", test_summaries),
        ]
    )
    validate_manifest(manifest)
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    generate_index_html(run_dir)
    return run_dir


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--tests", type=int, default=30)
    p.add_argument("--fail-rate", type=float, default=0.15)
    p.add_argument("--steps-per-test", type=int, default=8)
    p.add_argument("--out", type=Path, default=Path("captures"))
    p.add_argument("--seed", type=int, default=None)
    args = p.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    run_dir = make_sample(args.out, args.tests, args.fail_rate, args.steps_per_test, args.seed)
    print(run_dir)


if __name__ == "__main__":
    main()
