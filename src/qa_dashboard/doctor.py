"""qa-dashboard run-directory health check.

Validates a run directory produced by any qa-dashboard capture path
(pytest plugin, Playwright reporter, WDIO reporter, JUnit/HAR ingest)
against the on-disk schema, and cross-references between the manifest,
per-test records, screenshots, and flows.

Designed to be a fast pre-flight check before publishing a report:

    qa-dashboard doctor captures/run_*

Exits 0 if everything looks fine, 1 if any problem was found.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .bundle.schemas import (
    BundleValidationError,
    validate_manifest,
    validate_test_record,
)

__all__ = ["Diagnosis", "diagnose", "format_report"]

_log = logging.getLogger("qa_dashboard.doctor")


@dataclass
class Diagnosis:
    """Result of inspecting a single run directory."""

    run_dir: Path
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: dict[str, Any] = field(default_factory=dict)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.ok = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


def diagnose(run_dir: Path) -> Diagnosis:
    """Inspect ``run_dir`` and return a :class:`Diagnosis`."""
    run_dir = Path(run_dir)
    d = Diagnosis(run_dir=run_dir)

    if not run_dir.exists() or not run_dir.is_dir():
        d.add_error(f"run directory does not exist: {run_dir}")
        return d

    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        d.add_error(f"missing manifest.json in {run_dir}")
        return d

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        d.add_error(f"manifest.json is not valid JSON: {e}")
        return d
    except OSError as e:
        d.add_error(f"cannot read manifest.json: {e}")
        return d

    try:
        validate_manifest(manifest)
    except BundleValidationError as e:
        d.add_error(f"manifest schema violation: {e}")

    d.info["run_id"] = manifest.get("run_id")
    d.info["schema_version"] = manifest.get("schema_version")
    d.info["total_tests"] = (manifest.get("summary") or {}).get("total")

    tests_dir = run_dir / "tests"
    if not tests_dir.exists():
        d.add_error(f"missing tests/ directory in {run_dir}")
        return d

    # Per-test validation + cross-references
    manifest_summaries = {t.get("test_id"): t for t in (manifest.get("tests") or [])}
    seen_test_ids: set[str] = set()
    total_flows = 0
    total_screenshots = 0
    missing_screenshot_files = 0

    for test_path in sorted(tests_dir.glob("*.json")):
        try:
            record = json.loads(test_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            d.add_error(f"{test_path.name}: invalid JSON: {e}")
            continue
        except OSError as e:
            d.add_error(f"{test_path.name}: cannot read: {e}")
            continue
        try:
            validate_test_record(record)
        except BundleValidationError as e:
            d.add_error(f"{test_path.name}: schema violation: {e}")
            continue

        tid = record.get("test_id")
        if tid is None:
            d.add_error(f"{test_path.name}: missing test_id")
            continue
        if tid in seen_test_ids:
            d.add_error(f"duplicate test_id: {tid}")
        seen_test_ids.add(tid)

        # Cross-reference with manifest summary
        summary = manifest_summaries.get(tid)
        if summary is None:
            d.add_warning(
                f"{tid}: present in tests/ but not in manifest.tests[]",
            )
        else:
            if summary.get("status") != record.get("status"):
                d.add_error(
                    f"{tid}: status mismatch — manifest={summary.get('status')!r} "
                    f"vs record={record.get('status')!r}"
                )

        # Cross-reference: screenshot files must exist on disk
        for shot in record.get("screenshots") or []:
            total_screenshots += 1
            asset_rel = shot.get("asset_path")
            if not asset_rel:
                d.add_warning(f"{tid}: screenshot {shot.get('id')!r} has no asset_path")
                continue
            asset = run_dir / asset_rel
            if not asset.exists():
                missing_screenshot_files += 1
                d.add_error(
                    f"{tid}: screenshot {shot.get('id')!r} asset missing on disk ({asset_rel})"
                )

        # Cross-reference: every step's flow_ids/screenshot_ids must
        # resolve to a real top-level flow/screenshot.
        flow_ids_in_record = {f.get("id") for f in (record.get("flows") or [])}
        shot_ids_in_record = {s.get("id") for s in (record.get("screenshots") or [])}
        total_flows += len(flow_ids_in_record)
        for step in record.get("steps") or []:
            for fid in step.get("flow_ids") or []:
                if fid not in flow_ids_in_record:
                    d.add_error(
                        f"{tid}: step {step.get('id')} references flow_id "
                        f"{fid!r} that is not in record.flows[]"
                    )
            for sid in step.get("screenshot_ids") or []:
                if sid not in shot_ids_in_record:
                    d.add_error(
                        f"{tid}: step {step.get('id')} references screenshot_id "
                        f"{sid!r} that is not in record.screenshots[]"
                    )

    # Catch tests in the manifest with no record on disk
    for tid in manifest_summaries:
        if tid not in seen_test_ids:
            d.add_error(f"manifest references test_id {tid!r} but tests/{tid}.json is missing")

    if d.info.get("total_tests") is not None and d.info["total_tests"] != len(seen_test_ids):
        d.add_warning(
            f"manifest.summary.total={d.info['total_tests']} but "
            f"{len(seen_test_ids)} test record(s) found on disk"
        )

    d.info["total_flows"] = total_flows
    d.info["total_screenshots"] = total_screenshots
    d.info["missing_screenshot_files"] = missing_screenshot_files

    # Surface any addon error log
    addon_err = run_dir / "_flows" / "_addon_errors.log"
    if addon_err.exists() and addon_err.stat().st_size > 0:
        d.add_warning(
            f"mitm addon error log is non-empty: {addon_err} (network capture may have lost flows)"
        )

    return d


def format_report(d: Diagnosis) -> str:
    """Render a Diagnosis as a human-readable report."""
    lines: list[str] = []
    lines.append(f"qa-dashboard doctor — {d.run_dir}")
    if d.info:
        info = ", ".join(f"{k}={v}" for k, v in d.info.items() if v is not None)
        if info:
            lines.append(f"  {info}")
    if d.errors:
        lines.append(f"  errors ({len(d.errors)}):")
        for e in d.errors:
            lines.append(f"    - {e}")
    if d.warnings:
        lines.append(f"  warnings ({len(d.warnings)}):")
        for w in d.warnings:
            lines.append(f"    - {w}")
    if not d.errors and not d.warnings:
        lines.append("  OK")
    return "\n".join(lines)
