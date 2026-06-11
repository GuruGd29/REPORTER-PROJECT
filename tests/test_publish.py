"""Tests for qa_dashboard.publish — static publishing & rollup."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from qa_dashboard.publish import (
    FilesystemPublisher,
    PublisherError,
    _build_rollup_index,
    _content_type_for,
    _iter_run_files,
    make_publisher,
    publish_static,
)

# --- run-dir fixture -------------------------------------------------------


@pytest.fixture
def sample_run(tmp_path: Path) -> Path:
    from tests.fixtures.make_sample_run import make_sample

    return make_sample(out_root=tmp_path, num_tests=3, fail_rate=0.34, steps_per_test=2, seed=11)


# --- destination parsing ---------------------------------------------------


def test_make_publisher_filesystem(tmp_path: Path):
    p = make_publisher(f"file://{tmp_path}")
    assert isinstance(p, FilesystemPublisher)
    assert p.root == tmp_path.resolve()


def test_make_publisher_bare_path_is_filesystem(tmp_path: Path):
    p = make_publisher(str(tmp_path))
    assert isinstance(p, FilesystemPublisher)


def test_make_publisher_s3_missing_bucket():
    with pytest.raises(PublisherError):
        make_publisher("s3://")


def test_make_publisher_unsupported_scheme():
    with pytest.raises(PublisherError):
        make_publisher("ftp://foo/bar")


# --- content type ---------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("index.html", "text/html"),
        ("manifest.json", "application/json"),
        ("foo.png", "image/png"),
        ("foo.jpg", "image/jpeg"),
        ("foo.webp", "image/webp"),
        ("foo.unknown", "application/octet-stream"),
    ],
)
def test_content_type_for(name: str, expected: str):
    assert _content_type_for(Path(name)) == expected


# --- skip filter ----------------------------------------------------------


def test_iter_run_files_skips_side_channels(sample_run: Path):
    # Plant artifacts that publish must NOT upload.
    (sample_run / "_flows").mkdir(exist_ok=True)
    (sample_run / "_flows" / "t001.jsonl").write_text("{}\n", encoding="utf-8")
    (sample_run / "_logs").mkdir(exist_ok=True)
    (sample_run / "_logs" / "t001.jsonl").write_text("{}\n", encoding="utf-8")
    (sample_run / "current.txt").write_text("", encoding="utf-8")

    paths = list(_iter_run_files(sample_run))
    rels = {p.relative_to(sample_run).as_posix() for p in paths}
    assert not any(r.startswith("_flows/") for r in rels)
    assert not any(r.startswith("_logs/") for r in rels)
    assert "current.txt" not in rels


# --- filesystem publish end-to-end ----------------------------------------


def test_publish_static_filesystem_creates_run_dir(sample_run: Path, tmp_path: Path):
    dest = tmp_path / "out"
    result = publish_static(sample_run, f"file://{dest}")
    assert result.files_uploaded > 0
    assert (dest / result.run_id / "index.html").exists()
    assert (dest / result.run_id / "manifest.json").exists()
    # Tests/ tree mirrored
    assert any(p.suffix == ".json" for p in (dest / result.run_id / "tests").iterdir())


def test_publish_static_writes_rollup_index(sample_run: Path, tmp_path: Path):
    dest = tmp_path / "out"
    publish_static(sample_run, f"file://{dest}")
    rollup = (dest / "index.html").read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in rollup
    assert sample_run.name in rollup or "run_" in rollup  # the run_id appears
    runs = json.loads((dest / "runs.json").read_text(encoding="utf-8"))
    assert runs["schema_version"] == 1
    assert len(runs["runs"]) == 1


def test_publish_static_skip_rollup(sample_run: Path, tmp_path: Path):
    dest = tmp_path / "out"
    publish_static(sample_run, f"file://{dest}", skip_rollup=True)
    assert not (dest / "index.html").exists()
    assert not (dest / "runs.json").exists()


def test_publish_static_dedupes_same_run(sample_run: Path, tmp_path: Path):
    dest = tmp_path / "out"
    publish_static(sample_run, f"file://{dest}")
    publish_static(sample_run, f"file://{dest}")  # second publish, same run_id
    runs = json.loads((dest / "runs.json").read_text(encoding="utf-8"))
    assert len(runs["runs"]) == 1


def test_publish_static_rollup_window_trims(sample_run: Path, tmp_path: Path, monkeypatch):
    dest = tmp_path / "out"
    # Seed an existing runs.json with N synthetic entries.
    dest.mkdir()
    existing = {
        "schema_version": 1,
        "runs": [
            {
                "run_id": f"run_old_{i:03d}",
                "status": "pass",
                "started_at": f"2026-05-{i + 1:02d}T00:00:00.000Z",
                "ended_at": f"2026-05-{i + 1:02d}T00:00:01.000Z",
                "duration_ms": 1000,
                "summary": {
                    "total": 1,
                    "passed": 1,
                    "failed": 0,
                    "skipped": 0,
                    "error": 0,
                    "pass_rate": 1.0,
                },
            }
            for i in range(8)
        ],
    }
    (dest / "runs.json").write_text(json.dumps(existing), encoding="utf-8")

    publish_static(sample_run, f"file://{dest}", rollup_window=5)
    runs = json.loads((dest / "runs.json").read_text(encoding="utf-8"))
    assert len(runs["runs"]) == 5
    # Newest first
    assert runs["runs"][0]["run_id"].startswith("run_")


def test_publish_static_missing_manifest_raises(tmp_path: Path):
    empty = tmp_path / "empty_run"
    empty.mkdir()
    with pytest.raises(PublisherError):
        publish_static(empty, f"file://{tmp_path / 'out'}")


# --- rollup template ------------------------------------------------------


def test_build_rollup_index_empty():
    html = _build_rollup_index([])
    assert "No runs published yet" in html


def test_build_rollup_index_renders_entries():
    entries = [
        {
            "run_id": "run_20260101_111111_abc",
            "status": "pass",
            "started_at": "2026-01-01T11:11:11.000Z",
            "duration_ms": 1234,
            "summary": {
                "total": 5,
                "passed": 4,
                "failed": 1,
                "skipped": 0,
                "error": 0,
                "pass_rate": 0.8,
            },
        }
    ]
    html = _build_rollup_index(entries)
    assert "run_20260101_111111_abc" in html
    assert "1.2 s" in html  # duration formatting
    assert "80%" in html


# --- S3 publisher (mocked) ------------------------------------------------


def test_s3_publisher_uses_public_acl_when_requested(monkeypatch):
    # boto3 is in the [dev,all,publish] extras; if it's not installed
    # in this environment, skip — publish_static still works via the
    # filesystem path.
    boto3 = pytest.importorskip("boto3")

    captured = {}

    def fake_put_object(**kwargs):
        captured.update(kwargs)
        return {}

    real_client = boto3.client

    def fake_boto_client(service, **kwargs):
        m = MagicMock()
        m.put_object.side_effect = fake_put_object
        m.get_object.side_effect = real_client(service, **kwargs).exceptions.NoSuchKey  # type: ignore[attr-defined]
        return m

    monkeypatch.setattr(boto3, "client", fake_boto_client)

    from qa_dashboard.publish import S3Publisher

    pub = S3Publisher(bucket="b", prefix="p", public=True)
    pub.put("x.html", b"<x/>", "text/html")
    assert captured["ACL"] == "public-read"
    assert captured["Bucket"] == "b"
    assert captured["Key"] == "p/x.html"
    assert captured["ContentType"] == "text/html"


def test_s3_publisher_omits_acl_when_not_public(monkeypatch):
    boto3 = pytest.importorskip("boto3")

    captured = {}

    def fake_put_object(**kwargs):
        captured.update(kwargs)
        return {}

    def fake_boto_client(service, **kwargs):
        m = MagicMock()
        m.put_object.side_effect = fake_put_object
        return m

    monkeypatch.setattr(boto3, "client", fake_boto_client)

    from qa_dashboard.publish import S3Publisher

    S3Publisher(bucket="b", prefix="", public=False).put("y.json", b"{}", "application/json")
    assert "ACL" not in captured
