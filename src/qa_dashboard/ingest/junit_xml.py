"""JUnit XML ingestor.

Reads test result files produced by Java (Surefire / Failsafe / TestNG /
JUnit 5), JavaScript (Jest, Mocha, Playwright JS via junit reporter), and
any other framework that emits the standard JUnit XML format.

Produces qa-dashboard's run directory layout (manifest.json,
tests/<id>.json, assets/screenshots/) so the HTML report can be
generated normally via ``qa-dashboard <run-dir>``.

Limitations:
  * No step/sub-step data — JUnit XML has no concept of steps.
  * No network flows — out-of-band.
  * Screenshots optionally attached via the screenshots_dir argument.
"""

from __future__ import annotations

import json
import re
import shutil
import xml.etree.ElementTree as ET
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

from .. import SCHEMA_VERSION
from .._manifest import collect_environment, collect_source
from .._paths import make_run_dir, sanitize_nodeid

__all__ = ["ingest_junit_xml"]


_TIMESTAMP_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"


def _now_iso() -> str:
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _parse_xml_timestamp(s: str | None) -> str | None:
    if not s:
        return None
    # Surefire emits e.g. "2026-05-23T11:00:35"; sometimes with Z; sometimes ISO 8601
    s = s.strip()
    try:
        if s.endswith("Z"):
            dt = datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    except (ValueError, TypeError):
        return None


def _seconds_to_ms(s: str | None) -> int:
    if not s:
        return 0
    try:
        return int(float(s) * 1000)
    except (ValueError, TypeError):
        return 0


def _testsuite_elements(root: ET.Element) -> list[ET.Element]:
    """Return all <testsuite> elements regardless of nesting depth."""
    if root.tag == "testsuite":
        return [root]
    return list(root.iter("testsuite"))


def _testcase_status(tc: ET.Element) -> tuple[str, dict]:
    """Return (status, outcome_dict) for a <testcase>."""
    failure = tc.find("failure")
    error = tc.find("error")
    skipped = tc.find("skipped")

    if failure is not None:
        msg = failure.get("message") or ""
        long = (failure.text or "").strip()
        outcome = OrderedDict(
            [
                ("phase", "call"),
                ("longrepr", long or msg),
                ("traceback_summary", msg or long.splitlines()[0] if long else None),
                ("stdout_tail", ""),
                ("stderr_tail", ""),
            ]
        )
        return "fail", outcome
    if error is not None:
        msg = error.get("message") or ""
        long = (error.text or "").strip()
        outcome = OrderedDict(
            [
                ("phase", "setup"),
                ("longrepr", long or msg),
                ("traceback_summary", msg or (long.splitlines()[0] if long else None)),
                ("stdout_tail", ""),
                ("stderr_tail", ""),
            ]
        )
        return "error", outcome
    if skipped is not None:
        msg = skipped.get("message") or (skipped.text or "").strip() or "skipped"
        outcome = OrderedDict(
            [
                ("phase", "setup"),
                ("longrepr", f"Skipped: {msg}"),
                ("traceback_summary", f"Skipped: {msg}"),
                ("stdout_tail", ""),
                ("stderr_tail", ""),
            ]
        )
        return "skip", outcome
    # Passed
    return "pass", OrderedDict(
        [
            ("phase", "call"),
            ("longrepr", None),
            ("traceback_summary", None),
            ("stdout_tail", ""),
            ("stderr_tail", ""),
        ]
    )


def _classname_to_file(classname: str) -> str:
    """Best-effort conversion of a Java/JS class to a relative file path."""
    if not classname:
        return ""
    # Drop the simple class name on the last dot — keep package as dir
    parts = classname.split(".")
    if len(parts) > 1:
        return "/".join(parts[:-1]) + "/" + parts[-1] + ".java"
    return classname


def _find_screenshots(shots_dir: Path | None, *aliases: str) -> list[Path]:
    """Return PNGs/JPGs in ``shots_dir`` whose filename OR any ancestor
    directory name mentions an alias.

    Walks recursively so Playwright JS-style ``test-results/<test-title>/
    test-failed-1.png`` layouts auto-attach: the parent dir name is the
    test title, which we use for matching even when the filename itself
    is generic.
    """
    if not shots_dir or not shots_dir.exists():
        return []
    norm_aliases = [
        a for a in (re.sub(r"[^A-Za-z0-9]", "_", x).strip("_").lower() for x in aliases if x) if a
    ]
    if not norm_aliases:
        return []
    matches: list[Path] = []
    for p in shots_dir.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in (".png", ".jpg", ".jpeg"):
            continue
        # Build a haystack from the filename + every ancestor dir up to shots_dir
        parts: list[str] = [p.stem]
        for ancestor in p.parents:
            if ancestor == shots_dir or ancestor == shots_dir.parent:
                break
            parts.append(ancestor.name)
        haystack = re.sub(r"[^A-Za-z0-9]", "_", "_".join(parts)).lower()
        if any(a in haystack for a in norm_aliases):
            matches.append(p)
    return sorted(matches)


def _system_out_lines(suite: ET.Element, case: ET.Element) -> list[dict]:
    """Pull <system-out> from the test case (or fall back to suite-level)."""
    src = case.find("system-out")
    if src is None or not (src.text or "").strip():
        src = suite.find("system-out")
    if src is None:
        return []
    text = src.text or ""
    out: list[dict] = []
    for line in text.splitlines():
        line = line.rstrip()
        if not line:
            continue
        # Heuristic level detection
        upper = line.upper()
        if "ERROR" in upper or "FATAL" in upper:
            lvl = "ERROR"
        elif "WARN" in upper:
            lvl = "WARN"
        elif "DEBUG" in upper or "TRACE" in upper:
            lvl = "DEBUG"
        else:
            lvl = "INFO"
        out.append(
            {
                "ts": _now_iso(),
                "level": lvl,
                "logger": "junit.system-out",
                "message": line,
            }
        )
    return out


def ingest_junit_xml(
    inputs: list[Path] | Path,
    out_root: Path,
    screenshots_dir: Path | None = None,
    repo_label: str | None = None,
) -> Path:
    """Ingest one or more JUnit XML files (or a directory of them).

    Returns the created run directory containing a manifest + per-test
    JSON records compatible with the qa-dashboard HTML generator.
    """
    if isinstance(inputs, (str, Path)):
        inputs = [Path(inputs)]
    xml_files: list[Path] = []
    for inp in inputs:
        inp = Path(inp)
        if inp.is_dir():
            xml_files.extend(sorted(inp.rglob("*.xml")))
        elif inp.is_file():
            xml_files.append(inp)
    if not xml_files:
        raise FileNotFoundError(f"No JUnit XML files found in {inputs}")

    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    run_id, run_dir = make_run_dir(out_root)

    test_records: list[dict] = []
    test_summaries: list[dict] = []
    earliest_ts: str | None = None
    latest_ts: str | None = None
    total_ms = 0
    seq = 0

    for xml_path in xml_files:
        try:
            tree = ET.parse(xml_path)
        except ET.ParseError:
            continue
        root = tree.getroot()
        suites = _testsuite_elements(root)
        for suite in suites:
            suite_ts = _parse_xml_timestamp(suite.get("timestamp"))
            for case in suite.findall("testcase"):
                seq += 1
                classname = case.get("classname") or ""
                name = case.get("name") or "(unnamed)"
                nodeid = f"{classname}::{name}" if classname else name
                test_id = f"t{seq:03d}_{sanitize_nodeid(nodeid)}"
                started_at = suite_ts or _now_iso()
                duration_ms = _seconds_to_ms(case.get("time"))
                ended_at = started_at  # JUnit doesn't track per-case end time
                status, outcome = _testcase_status(case)

                screenshots: list[dict] = []
                step_id = 1
                # Screenshot scan (Java-side common pattern: file name contains test method)
                shots = _find_screenshots(
                    screenshots_dir, name, nodeid, classname.split(".")[-1] if classname else ""
                )
                for i, src_path in enumerate(shots, start=1):
                    dst_name = f"{test_id}_step_{step_id}_{i:03d}{src_path.suffix.lower()}"
                    dst = run_dir / "assets" / "screenshots" / dst_name
                    shutil.copyfile(src_path, dst)
                    screenshots.append(
                        OrderedDict(
                            [
                                ("id", f"{test_id}_step_{step_id}_{i:03d}"),
                                ("step_id", step_id),
                                ("captured_at", started_at),
                                ("filename", dst_name),
                                ("asset_path", f"assets/screenshots/{dst_name}"),
                                ("width", None),
                                ("height", None),
                                ("size_bytes", dst.stat().st_size),
                                ("label", src_path.stem),
                            ]
                        )
                    )

                # Single "Test execution" pseudo-step
                steps = [
                    OrderedDict(
                        [
                            ("id", 1),
                            ("name", "Test execution"),
                            ("status", status if status in ("pass", "fail", "skip") else "fail"),
                            ("started_at", started_at),
                            ("ended_at", ended_at),
                            ("duration_ms", duration_ms),
                            ("substeps", []),
                            ("screenshot_ids", [s["id"] for s in screenshots]),
                            ("flow_ids", []),
                            (
                                "error",
                                (
                                    {
                                        "type": "AssertionError" if status == "fail" else "Error",
                                        "message": (outcome.get("traceback_summary") or "")[:500],
                                        "traceback": outcome.get("longrepr") or "",
                                    }
                                    if status in ("fail", "error")
                                    else None
                                ),
                            ),
                            (
                                "skip_reason",
                                outcome.get("traceback_summary") if status == "skip" else None,
                            ),
                        ]
                    )
                ]

                console = _system_out_lines(suite, case)

                record = OrderedDict(
                    [
                        ("schema_version", SCHEMA_VERSION),
                        ("test_id", test_id),
                        ("nodeid", nodeid),
                        ("name", name),
                        ("file", _classname_to_file(classname)),
                        ("line", None),
                        ("status", status),
                        ("started_at", started_at),
                        ("ended_at", ended_at),
                        ("duration_ms", duration_ms),
                        ("tags", []),
                        ("parameters", None),
                        ("outcome", outcome),
                        ("steps", steps),
                        ("flows", []),
                        ("screenshots", screenshots),
                        ("console", console),
                        ("device", None),
                        ("app", None),
                    ]
                )
                test_records.append(record)
                test_summaries.append(
                    OrderedDict(
                        [
                            ("test_id", test_id),
                            ("nodeid", nodeid),
                            ("name", name),
                            ("file", _classname_to_file(classname)),
                            ("status", status),
                            ("started_at", started_at),
                            ("duration_ms", duration_ms),
                            ("step_count", 1),
                            ("flow_count", 0),
                            ("screenshot_count", len(screenshots)),
                            ("tags", []),
                            ("error_summary", outcome.get("traceback_summary")),
                        ]
                    )
                )

                if earliest_ts is None or started_at < earliest_ts:
                    earliest_ts = started_at
                if latest_ts is None or started_at > latest_ts:
                    latest_ts = started_at
                total_ms += duration_ms

    # Write per-test JSON files
    for record in test_records:
        out_path = run_dir / "tests" / f"{record['test_id']}.json"
        out_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    # Build manifest
    summary = {
        "total": len(test_summaries),
        "passed": sum(1 for t in test_summaries if t["status"] == "pass"),
        "failed": sum(1 for t in test_summaries if t["status"] == "fail"),
        "skipped": sum(1 for t in test_summaries if t["status"] == "skip"),
        "error": sum(1 for t in test_summaries if t["status"] == "error"),
        "xfailed": 0,
        "xpassed": 0,
    }
    summary["pass_rate"] = round(summary["passed"] / max(summary["total"], 1), 3)
    if summary["error"] > 0:
        status = "error"
    elif summary["failed"] > 0:
        status = "fail"
    elif summary["total"] == 0:
        status = "pass"
    else:
        status = "pass"

    env = collect_environment()
    env["pytest"] = None  # not a pytest run
    src = collect_source()
    if repo_label:
        src["repo"] = repo_label

    manifest = OrderedDict(
        [
            ("schema_version", SCHEMA_VERSION),
            ("run_id", run_id),
            ("started_at", earliest_ts or _now_iso()),
            ("ended_at", latest_ts or _now_iso()),
            ("duration_ms", total_ms),
            ("status", status),
            ("summary", summary),
            ("environment", env),
            ("source", src),
            (
                "config",
                {
                    "ingestor": "junit-xml",
                    "inputs": [str(p) for p in xml_files],
                    "screenshots_dir": str(screenshots_dir) if screenshots_dir else None,
                    "command_line": "",
                },
            ),
            ("tests", test_summaries),
        ]
    )
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return run_dir
