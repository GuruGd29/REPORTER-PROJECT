from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .report.export import EXPORTERS, export
from .report.generator import generate_index_html, generate_standalone_test_html


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    # Dispatch on first positional. Subcommands ("ingest") take their own
    # parser; everything else uses the legacy "qa-dashboard <run-dir> ..."
    # form. This avoids argparse subparser/positional ambiguity.
    if argv and argv[0] == "ingest":
        return _cmd_ingest(argv[1:])
    return _cmd_default(argv)


def _cmd_ingest(argv: list[str]) -> int:
    from .ingest.junit_xml import ingest_junit_xml

    p = argparse.ArgumentParser(
        prog="qa-dashboard ingest",
        description=(
            "Ingest test results from a non-pytest framework (JUnit XML). "
            "Works with Maven Surefire / Failsafe, Gradle, TestNG, JUnit 5, "
            "Jest junit reporter, Playwright JS junit reporter, etc."
        ),
    )
    p.add_argument("inputs", nargs="+", type=Path,
                   help="JUnit XML files or directory(ies) containing them")
    p.add_argument("-o", "--out", type=Path, default=Path("captures"),
                   help="Root directory for the generated run (default: captures)")
    p.add_argument("--screenshots-dir", type=Path, default=None,
                   help="Directory of PNGs to attach by filename match")
    p.add_argument("--format", choices=["junit-xml"], default="junit-xml",
                   help="Input format (currently only junit-xml)")
    p.add_argument("--repo", default=None, help="Repository label to record")
    p.add_argument("--no-report", action="store_true",
                   help="Skip HTML generation (only write JSON artifacts)")
    p.add_argument("--brand-color", default=None, help="HTML brand color")
    args = p.parse_args(argv)

    try:
        run_dir = ingest_junit_xml(
            inputs=args.inputs,
            out_root=args.out,
            screenshots_dir=args.screenshots_dir,
            repo_label=args.repo,
        )
    except FileNotFoundError as e:
        print(f"qa-dashboard: {e}", file=sys.stderr)
        return 2
    print(f"Ingested {len(args.inputs)} input(s) -> {run_dir}")
    if not args.no_report:
        out = generate_index_html(run_dir, brand_color=args.brand_color)
        print(f"Generated {out}")
    return 0


def _cmd_default(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        prog="qa-dashboard",
        description=(
            "Generate, regenerate, or export a qa-dashboard report. "
            "Use `qa-dashboard ingest <xml>` to import JUnit XML from Java/JS."
        ),
    )
    p.add_argument("--version", action="version", version=f"qa-dashboard {__version__}")
    p.add_argument("run_dir", type=Path,
                   help="Path to a qa-dashboard run directory")
    p.add_argument("--test", default=None,
                   help="Render a standalone HTML for a single test_id")
    p.add_argument("--brand-color", default=None,
                   help="Override the brand accent color (e.g. #1d4ed8)")
    p.add_argument("--export", choices=sorted(EXPORTERS.keys()), default=None,
                   help="Export the run to another format")
    p.add_argument("-o", "--output", type=Path, default=None,
                   help="Output file for --export")
    p.add_argument("--force", action="store_true",
                   help="Regenerate even if index.html exists")
    args = p.parse_args(argv)

    run_dir = args.run_dir
    if not run_dir.exists():
        print(f"qa-dashboard: no such directory: {run_dir}", file=sys.stderr)
        return 2
    if not (run_dir / "manifest.json").exists():
        print(f"qa-dashboard: no manifest.json in {run_dir}", file=sys.stderr)
        return 2

    if args.export:
        out = args.output
        if out is None:
            import json as _json
            mid = _json.loads((run_dir / "manifest.json").read_text())["run_id"]
            out = run_dir / "exports" / f"{mid}.{args.export}"
        try:
            written = export(run_dir, args.export, out)
        except ImportError as e:
            print(f"qa-dashboard: {e}", file=sys.stderr)
            return 3
        except (FileNotFoundError, ValueError) as e:
            print(f"qa-dashboard: {e}", file=sys.stderr)
            return 2
        print(f"Exported: {written}")
        return 0

    if args.test:
        try:
            out = generate_standalone_test_html(run_dir, args.test)
        except FileNotFoundError as e:
            print(f"qa-dashboard: {e}", file=sys.stderr)
            return 2
        print(f"Generated {out}")
        return 0

    out = generate_index_html(run_dir, brand_color=args.brand_color)
    print(f"Generated {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
