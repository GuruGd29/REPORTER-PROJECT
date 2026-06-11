"""Unit tests for qa_dashboard.doctor."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from qa_dashboard.doctor import diagnose, format_report


@pytest.fixture
def healthy_run(tmp_path: Path) -> Path:
    from tests.fixtures.make_sample_run import make_sample

    return make_sample(
        out_root=tmp_path,
        num_tests=3,
        fail_rate=0.0,
        steps_per_test=2,
        seed=1,
    )


def test_diagnose_healthy_run_returns_ok(healthy_run: Path):
    d = diagnose(healthy_run)
    assert d.ok is True
    assert d.errors == []
    assert d.info["total_tests"] == 3


def test_diagnose_missing_directory(tmp_path: Path):
    d = diagnose(tmp_path / "does-not-exist")
    assert d.ok is False
    assert any("does not exist" in e for e in d.errors)


def test_diagnose_missing_manifest(tmp_path: Path):
    run = tmp_path / "broken_run"
    run.mkdir()
    d = diagnose(run)
    assert d.ok is False
    assert any("manifest.json" in e for e in d.errors)


def test_diagnose_corrupt_manifest_json(tmp_path: Path):
    run = tmp_path / "corrupt_run"
    (run / "tests").mkdir(parents=True)
    (run / "manifest.json").write_text("{not json", encoding="utf-8")
    d = diagnose(run)
    assert d.ok is False
    assert any("not valid JSON" in e for e in d.errors)


def test_diagnose_detects_orphan_test_in_manifest(healthy_run: Path):
    manifest = json.loads((healthy_run / "manifest.json").read_text())
    manifest["tests"].append(
        {
            "test_id": "t999_ghost",
            "nodeid": "ghost",
            "name": "ghost",
            "file": "",
            "status": "pass",
            "started_at": "2026-01-01T00:00:00.000Z",
            "duration_ms": 0,
            "step_count": 0,
            "flow_count": 0,
            "screenshot_count": 0,
            "tags": [],
            "error_summary": None,
        }
    )
    (healthy_run / "manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    d = diagnose(healthy_run)
    assert d.ok is False
    assert any("ghost" in e for e in d.errors)


def test_diagnose_detects_missing_screenshot_file(tmp_path: Path):
    from tests.fixtures.make_sample_run import make_sample

    run = make_sample(
        out_root=tmp_path,
        num_tests=2,
        fail_rate=1.0,
        steps_per_test=2,
        seed=2,
    )
    # Wipe one screenshot asset.
    shots = sorted((run / "assets" / "screenshots").iterdir())
    if shots:
        shots[0].unlink()
        d = diagnose(run)
        assert d.ok is False
        assert any("asset missing on disk" in e for e in d.errors)


def test_format_report_includes_run_info(healthy_run: Path):
    out = format_report(diagnose(healthy_run))
    assert "qa-dashboard doctor" in out
    assert "OK" in out


def test_diagnose_warns_on_nonempty_addon_error_log(healthy_run: Path):
    flows_dir = healthy_run / "_flows"
    flows_dir.mkdir(exist_ok=True)
    (flows_dir / "_addon_errors.log").write_text(
        "Traceback...\n",
        encoding="utf-8",
    )
    d = diagnose(healthy_run)
    assert d.ok is True  # warnings only, not errors
    assert any("addon error log" in w for w in d.warnings)
