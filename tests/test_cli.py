"""CLI smoke tests."""

from __future__ import annotations

import json
from pathlib import Path

from qa_dashboard.cli import _detect_ingest_format, main


def test_cli_version_exits_zero(capsys):
    rc = -1
    try:
        main(["--help"])
    except SystemExit as e:
        rc = e.code
    assert rc == 0


def test_detect_format_picks_har_for_har_extension(tmp_path: Path):
    p = tmp_path / "trace.har"
    p.write_text("{}", encoding="utf-8")
    assert _detect_ingest_format([p]) == "har"


def test_detect_format_picks_junit_for_xml_extension(tmp_path: Path):
    p = tmp_path / "junit.xml"
    p.write_text("<x/>", encoding="utf-8")
    assert _detect_ingest_format([p]) == "junit-xml"


def test_detect_format_defaults_to_junit_when_mixed(tmp_path: Path):
    p1 = tmp_path / "a.har"
    p2 = tmp_path / "b.xml"
    p1.write_text("{}", encoding="utf-8")
    p2.write_text("<x/>", encoding="utf-8")
    assert _detect_ingest_format([p1, p2]) == "junit-xml"


def test_cli_doctor_subcommand_runs(tmp_path, capsys):
    from tests.fixtures.make_sample_run import make_sample

    run = make_sample(
        out_root=tmp_path,
        num_tests=2,
        fail_rate=0.0,
        steps_per_test=2,
        seed=42,
    )
    rc = main(["doctor", str(run)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "qa-dashboard doctor" in out


def test_cli_doctor_returns_nonzero_on_broken_run(tmp_path, capsys):
    run = tmp_path / "broken"
    run.mkdir()
    rc = main(["doctor", str(run)])
    assert rc == 1


def test_cli_ingest_har(tmp_path, capsys):
    har_path = tmp_path / "t.har"
    har_path.write_text(
        json.dumps(
            {
                "log": {
                    "version": "1.2",
                    "creator": {"name": "x", "version": "1"},
                    "entries": [
                        {
                            "startedDateTime": "2026-05-27T10:00:00.000Z",
                            "time": 5,
                            "request": {
                                "method": "GET",
                                "url": "https://x.example/y",
                                "httpVersion": "HTTP/2",
                                "headers": [],
                                "queryString": [],
                                "cookies": [],
                                "headersSize": -1,
                                "bodySize": 0,
                            },
                            "response": {
                                "status": 200,
                                "statusText": "OK",
                                "httpVersion": "HTTP/2",
                                "headers": [],
                                "cookies": [],
                                "content": {"size": 0, "mimeType": ""},
                                "redirectURL": "",
                                "headersSize": -1,
                                "bodySize": 0,
                            },
                            "cache": {},
                            "timings": {"send": 0, "wait": 5, "receive": 0},
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    rc = main(["ingest", str(har_path), "-o", str(tmp_path / "out"), "--no-report"])
    assert rc == 0
    runs = list((tmp_path / "out").glob("run_*"))
    assert len(runs) == 1
