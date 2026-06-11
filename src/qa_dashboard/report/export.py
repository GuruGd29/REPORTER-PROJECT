"""Multi-format export for qa-dashboard runs.

Public API:

    export_csv(run_dir, out_path)
    export_json(run_dir, out_path)
    export_zip(run_dir, out_path)
    export_xlsx(run_dir, out_path)       # requires openpyxl
    export_docx(run_dir, out_path)       # requires python-docx

CLI integration: see ``qa_dashboard.cli.main``.
"""

from __future__ import annotations

import csv
import json
import zipfile
from collections import OrderedDict
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_manifest(run_dir: Path) -> dict:
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"No manifest.json in {run_dir}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _load_test_records(run_dir: Path) -> list[dict]:
    tests_dir = run_dir / "tests"
    if not tests_dir.exists():
        return []
    out = []
    for p in sorted(tests_dir.glob("*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return out


def _row_for_test(t: dict) -> OrderedDict:
    return OrderedDict(
        [
            ("test_id", t.get("test_id", "")),
            ("nodeid", t.get("nodeid", "")),
            ("name", t.get("name", "")),
            ("file", t.get("file", "")),
            ("status", t.get("status", "")),
            ("started_at", t.get("started_at", "")),
            ("duration_ms", t.get("duration_ms", 0)),
            ("step_count", t.get("step_count", 0)),
            ("flow_count", t.get("flow_count", 0)),
            ("screenshot_count", t.get("screenshot_count", 0)),
            ("tags", ", ".join(t.get("tags") or [])),
            ("error_summary", t.get("error_summary") or ""),
        ]
    )


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


def export_csv(run_dir: Path, out_path: Path) -> Path:
    """Export the test summary as a CSV (opens directly in Excel/Numbers)."""
    run_dir = Path(run_dir)
    out_path = Path(out_path)
    manifest = _load_manifest(run_dir)
    rows = [_row_for_test(t) for t in manifest.get("tests", [])]
    fieldnames = list(rows[0].keys()) if rows else list(_row_for_test({}).keys())
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    return out_path


# ---------------------------------------------------------------------------
# JSON (bundles manifest + all test records into one file)
# ---------------------------------------------------------------------------


def export_json(run_dir: Path, out_path: Path) -> Path:
    """Export the full run as a single JSON file (manifest + all test records)."""
    run_dir = Path(run_dir)
    out_path = Path(out_path)
    bundle = {
        "manifest": _load_manifest(run_dir),
        "tests": _load_test_records(run_dir),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# ZIP (whole run directory)
# ---------------------------------------------------------------------------


def export_zip(run_dir: Path, out_path: Path) -> Path:
    """Zip the whole run directory so it can be emailed/shared."""
    run_dir = Path(run_dir)
    out_path = Path(out_path)
    if out_path.suffix.lower() != ".zip":
        out_path = out_path.with_suffix(".zip")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in run_dir.rglob("*"):
            if path.is_file():
                # Skip the side-channel and intermediate dirs
                rel = path.relative_to(run_dir)
                if rel.parts and rel.parts[0] in {"_flows", "_logs"}:
                    continue
                if rel.name in {"current.txt", "current.tmp", "manifest.tmp"}:
                    continue
                zf.write(path, arcname=str(rel))
    return out_path


# ---------------------------------------------------------------------------
# XLSX (requires openpyxl)
# ---------------------------------------------------------------------------

_STATUS_FILL = {
    "pass": "C6EFCE",
    "fail": "FFC7CE",
    "skip": "FFEB9C",
    "error": "FFC7CE",
}


def export_xlsx(run_dir: Path, out_path: Path) -> Path:
    """Export a rich Excel workbook with summary + per-test detail tabs."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError as e:
        raise ImportError(
            "openpyxl is required for XLSX export. Install with: pip install qa-dashboard[xlsx]"
        ) from e

    run_dir = Path(run_dir)
    out_path = Path(out_path)
    manifest = _load_manifest(run_dir)
    records = _load_test_records(run_dir)
    record_by_id = {r["test_id"]: r for r in records}

    wb = Workbook()

    # ----- Sheet 1: Summary -----
    ws = wb.active
    ws.title = "Summary"
    s = manifest.get("summary", {})
    env = manifest.get("environment", {})
    src = manifest.get("source", {})
    ws["A1"] = "qa-dashboard report"
    ws["A1"].font = Font(size=14, bold=True)
    rows = [
        ("Run ID", manifest.get("run_id", "")),
        ("Status", manifest.get("status", "")),
        ("Started at", manifest.get("started_at", "")),
        ("Ended at", manifest.get("ended_at", "")),
        ("Duration (ms)", manifest.get("duration_ms", 0)),
        ("", ""),
        ("Total", s.get("total", 0)),
        ("Passed", s.get("passed", 0)),
        ("Failed", s.get("failed", 0)),
        ("Skipped", s.get("skipped", 0)),
        ("Errors", s.get("error", 0)),
        ("Pass rate", f"{(s.get('pass_rate', 0) * 100):.1f}%"),
        ("", ""),
        ("Python", env.get("python", "")),
        ("Pytest", env.get("pytest", "")),
        ("Platform", env.get("platform", "")),
        ("qa_dashboard", env.get("qa_dashboard", "")),
        ("Repo", src.get("repo", "")),
        ("Branch", src.get("branch", "")),
        ("Commit", src.get("commit", "")),
    ]
    for i, (k, v) in enumerate(rows, start=3):
        ws.cell(row=i, column=1, value=k).font = Font(bold=bool(k))
        ws.cell(row=i, column=2, value=v)
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 50

    # ----- Sheet 2: Tests -----
    ws2 = wb.create_sheet("Tests")
    headers = [
        "#",
        "test_id",
        "name",
        "file",
        "status",
        "duration_ms",
        "steps",
        "API calls",
        "screenshots",
        "tags",
        "error_summary",
    ]
    for i, h in enumerate(headers, start=1):
        c = ws2.cell(row=1, column=i, value=h)
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="EEEEEE")
        c.alignment = Alignment(horizontal="left")
    widths = [4, 30, 30, 30, 8, 12, 8, 10, 13, 18, 60]
    for i, w in enumerate(widths, start=1):
        ws2.column_dimensions[get_column_letter(i)].width = w
    for r, t in enumerate(manifest.get("tests", []), start=2):
        cells = [
            r - 1,
            t.get("test_id", ""),
            t.get("name", ""),
            t.get("file", ""),
            t.get("status", ""),
            t.get("duration_ms", 0),
            t.get("step_count", 0),
            t.get("flow_count", 0),
            t.get("screenshot_count", 0),
            ", ".join(t.get("tags") or []),
            t.get("error_summary") or "",
        ]
        for c_idx, val in enumerate(cells, start=1):
            cell = ws2.cell(row=r, column=c_idx, value=val)
            if c_idx == 5:  # status column
                color = _STATUS_FILL.get(t.get("status"))
                if color:
                    cell.fill = PatternFill("solid", fgColor=color)
    ws2.freeze_panes = "A2"

    # ----- Sheet 3: Steps (one row per step across all tests) -----
    ws3 = wb.create_sheet("Steps")
    headers3 = [
        "test_id",
        "test_name",
        "step_id",
        "step_name",
        "status",
        "duration_ms",
        "substeps",
        "screenshots",
        "API calls",
        "error_type",
        "error_message",
    ]
    for i, h in enumerate(headers3, start=1):
        c = ws3.cell(row=1, column=i, value=h)
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="EEEEEE")
    widths3 = [25, 30, 6, 35, 8, 12, 10, 12, 10, 22, 60]
    for i, w in enumerate(widths3, start=1):
        ws3.column_dimensions[get_column_letter(i)].width = w
    row_idx = 2
    for t in manifest.get("tests", []):
        rec = record_by_id.get(t["test_id"], {})
        for step in rec.get("steps", []):
            err = step.get("error") or {}
            vals = [
                t["test_id"],
                t["name"],
                step.get("id"),
                step.get("name"),
                step.get("status"),
                step.get("duration_ms", 0),
                len(step.get("substeps", [])),
                len(step.get("screenshot_ids", [])),
                len(step.get("flow_ids", [])),
                err.get("type", "") if isinstance(err, dict) else "",
                err.get("message", "") if isinstance(err, dict) else "",
            ]
            for c_idx, val in enumerate(vals, start=1):
                cell = ws3.cell(row=row_idx, column=c_idx, value=val)
                if c_idx == 5:
                    color = _STATUS_FILL.get(step.get("status"))
                    if color:
                        cell.fill = PatternFill("solid", fgColor=color)
            row_idx += 1
    ws3.freeze_panes = "A2"

    # ----- Sheet 4: Network -----
    ws4 = wb.create_sheet("Network")
    headers4 = [
        "test_id",
        "step_id",
        "method",
        "host",
        "path",
        "status_code",
        "duration_ms",
        "timestamp",
    ]
    for i, h in enumerate(headers4, start=1):
        c = ws4.cell(row=1, column=i, value=h)
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="EEEEEE")
    widths4 = [25, 8, 8, 22, 50, 6, 12, 24]
    for i, w in enumerate(widths4, start=1):
        ws4.column_dimensions[get_column_letter(i)].width = w
    row_idx = 2
    for t in manifest.get("tests", []):
        rec = record_by_id.get(t["test_id"], {})
        for f in rec.get("flows", []):
            ws4.cell(row=row_idx, column=1, value=t["test_id"])
            ws4.cell(row=row_idx, column=2, value=f.get("step_id"))
            ws4.cell(row=row_idx, column=3, value=f.get("method"))
            ws4.cell(row=row_idx, column=4, value=f.get("host"))
            ws4.cell(row=row_idx, column=5, value=f.get("path"))
            ws4.cell(row=row_idx, column=6, value=f.get("status_code"))
            ws4.cell(row=row_idx, column=7, value=f.get("duration_ms"))
            ws4.cell(row=row_idx, column=8, value=f.get("timestamp"))
            row_idx += 1
    ws4.freeze_panes = "A2"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.suffix.lower() != ".xlsx":
        out_path = out_path.with_suffix(".xlsx")
    wb.save(str(out_path))
    return out_path


# ---------------------------------------------------------------------------
# DOCX (requires python-docx)
# ---------------------------------------------------------------------------


def export_docx(run_dir: Path, out_path: Path) -> Path:
    """Export a Word document with summary + per-test detail sections."""
    try:
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Inches, Pt
    except ImportError as e:
        raise ImportError(
            "python-docx is required for DOCX export. Install with: pip install qa-dashboard[docx]"
        ) from e

    run_dir = Path(run_dir)
    out_path = Path(out_path)
    manifest = _load_manifest(run_dir)
    records = _load_test_records(run_dir)
    record_by_id = {r["test_id"]: r for r in records}

    doc = Document()

    # Title
    t = doc.add_heading("Test Run Report", level=0)
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # Summary block
    s = manifest.get("summary", {})
    env = manifest.get("environment", {})
    src = manifest.get("source", {})
    doc.add_paragraph(f"Run ID: {manifest.get('run_id', '')}")
    doc.add_paragraph(f"Status: {manifest.get('status', '')}")
    doc.add_paragraph(f"Started: {manifest.get('started_at', '')}")
    doc.add_paragraph(f"Duration: {manifest.get('duration_ms', 0)} ms")
    if src.get("branch") or src.get("commit"):
        doc.add_paragraph(f"Source: branch {src.get('branch', '')} commit {src.get('commit', '')}")

    doc.add_heading("Summary", level=1)
    tbl = doc.add_table(rows=1, cols=2)
    tbl.style = "Light Grid"
    hdr = tbl.rows[0].cells
    hdr[0].text = "Metric"
    hdr[1].text = "Value"
    for k, v in [
        ("Total", s.get("total", 0)),
        ("Passed", s.get("passed", 0)),
        ("Failed", s.get("failed", 0)),
        ("Skipped", s.get("skipped", 0)),
        ("Errors", s.get("error", 0)),
        ("Pass rate", f"{(s.get('pass_rate', 0) * 100):.1f}%"),
        ("Python", env.get("python", "")),
        ("Pytest", env.get("pytest", "")),
        ("Platform", env.get("platform", "")),
    ]:
        row = tbl.add_row().cells
        row[0].text = str(k)
        row[1].text = str(v)

    # Test list
    doc.add_heading("Tests", level=1)
    test_tbl = doc.add_table(rows=1, cols=5)
    test_tbl.style = "Light Grid"
    headers = test_tbl.rows[0].cells
    for i, h in enumerate(["#", "Name", "Status", "Duration (ms)", "Error"]):
        headers[i].text = h
    for i, t_summary in enumerate(manifest.get("tests", []), start=1):
        row = test_tbl.add_row().cells
        row[0].text = str(i)
        row[1].text = t_summary.get("name", "")
        row[2].text = t_summary.get("status", "")
        row[3].text = str(t_summary.get("duration_ms", 0))
        row[4].text = (t_summary.get("error_summary") or "")[:200]

    # Failed-test detail (only failed/error to keep doc readable)
    failed = [t for t in manifest.get("tests", []) if t.get("status") in ("fail", "error")]
    if failed:
        doc.add_page_break()
        doc.add_heading("Failed test details", level=1)
        for t_summary in failed:
            rec = record_by_id.get(t_summary["test_id"])
            if not rec:
                continue
            doc.add_heading(t_summary.get("name", ""), level=2)
            doc.add_paragraph(t_summary.get("nodeid", ""))
            err = (rec.get("outcome") or {}).get("longrepr") or ""
            if err:
                p = doc.add_paragraph()
                run = p.add_run(err[:2000])
                run.font.name = "Courier New"
                run.font.size = Pt(9)
            # Inline first failed step's screenshots (if any)
            for step in rec.get("steps", []):
                if step.get("status") != "fail":
                    continue
                doc.add_paragraph(f"Step {step['id']}: {step['name']}", style="Intense Quote")
                for shot_id in step.get("screenshot_ids", []):
                    shot = next((s for s in rec.get("screenshots", []) if s["id"] == shot_id), None)
                    if not shot:
                        continue
                    asset = run_dir / shot["asset_path"]
                    if asset.exists():
                        try:
                            doc.add_picture(str(asset), width=Inches(4.0))
                            if shot.get("label"):
                                doc.add_paragraph(shot["label"]).italic = True
                        except Exception:
                            pass
                break  # only the first failed step's screenshots

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.suffix.lower() != ".docx":
        out_path = out_path.with_suffix(".docx")
    doc.save(str(out_path))
    return out_path


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

EXPORTERS = {
    "csv": export_csv,
    "json": export_json,
    "zip": export_zip,
    "xlsx": export_xlsx,
    "docx": export_docx,
}


def export(run_dir: Path, fmt: str, out_path: Path) -> Path:
    fmt = fmt.lower()
    if fmt not in EXPORTERS:
        raise ValueError(f"Unknown export format {fmt!r}. Supported: {sorted(EXPORTERS.keys())}")
    return EXPORTERS[fmt](Path(run_dir), Path(out_path))
