"""Static publishing of qa-dashboard runs.

The Allure-style hosting model: take a run directory, upload everything
as static files to a destination (S3-compatible bucket or a local
filesystem path), maintain a rolling `index.html` listing the most
recent runs at the bucket root.

Destinations
------------

* ``s3://bucket[/prefix]`` — S3-compatible. Works with AWS S3,
  Cloudflare R2, Backblaze B2, MinIO, and anything else that speaks
  the S3 API. Requires the ``[publish]`` extra (`pip install
  qa-dashboard[publish]`) for `boto3`. AWS-style env vars
  (``AWS_ACCESS_KEY_ID``, ``AWS_SECRET_ACCESS_KEY``,
  ``AWS_DEFAULT_REGION``) work by default; pass overrides via
  :func:`publish_static`'s ``s3_kwargs``.
* ``file:///absolute/path`` — local filesystem; useful for testing
  with ``python -m http.server`` or for the gh-pages-via-rsync flow.

Layout written at the destination
---------------------------------

::

    <prefix>/
        index.html                 # rollup of recent runs
        runs.json                  # machine-readable rollup
        <run_id>/
            index.html             # the run's full HTML report
            manifest.json
            tests/*.json
            assets/screenshots/*

The rollup is read-modify-write: each publish reads the current
``runs.json``, prepends the new run, trims to ``rollup_window`` (default
50), and writes both ``runs.json`` and a fresh ``index.html``.

CLI
---

::

    qa-dashboard publish-static <run-dir> --to <destination> [options]
"""

from __future__ import annotations

import html
import json
import logging
import mimetypes
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

__all__ = [
    "FilesystemPublisher",
    "PublishResult",
    "Publisher",
    "PublisherError",
    "S3Publisher",
    "make_publisher",
    "publish_static",
]

_log = logging.getLogger("qa_dashboard.publish")

# Files we never upload (mitm side channel, log JSONLs, tempfiles).
_SKIP_DIRS = frozenset({"_flows", "_logs"})
_SKIP_NAMES = frozenset({"current.txt", "current.tmp", "manifest.tmp"})


class PublisherError(RuntimeError):
    """Raised when publishing fails for a reason worth surfacing to the user."""


@dataclass(frozen=True)
class PublishResult:
    """Returned by :func:`publish_static`."""

    run_id: str
    destination: str
    run_url: str | None
    rollup_url: str | None
    files_uploaded: int


# ---------------------------------------------------------------------------
# Publisher interface
# ---------------------------------------------------------------------------


class Publisher(ABC):
    """Minimal interface every destination implements."""

    @abstractmethod
    def put(self, key: str, body: bytes, content_type: str) -> None: ...

    @abstractmethod
    def get(self, key: str) -> bytes | None:
        """Return the bytes at ``key`` or ``None`` if not present."""

    @abstractmethod
    def public_url(self, key: str) -> str | None:
        """Best-effort public URL for ``key``; may return ``None`` if
        the destination cannot guess one (e.g. filesystem)."""

    def describe(self) -> str:
        """Short human-readable description of the destination."""
        return self.__class__.__name__


class FilesystemPublisher(Publisher):
    """Writes objects to a directory on disk."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def put(self, key: str, body: bytes, content_type: str) -> None:
        dst = self._root / key
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(body)

    def get(self, key: str) -> bytes | None:
        p = self._root / key
        if not p.exists():
            return None
        return p.read_bytes()

    def public_url(self, key: str) -> str | None:
        return (self._root / key).as_uri()

    def describe(self) -> str:
        return f"filesystem at {self._root}"


class S3Publisher(Publisher):
    """Writes objects to any S3-compatible bucket.

    Lazy-imports boto3 so it's only required when the user actually
    publishes to S3 — ``qa-dashboard[publish]`` controls the install.
    """

    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        *,
        public: bool = False,
        access_key: str | None = None,
        secret_key: str | None = None,
        region: str | None = None,
        endpoint_url: str | None = None,
        force_path_style: bool = False,
    ) -> None:
        try:
            import boto3
            from botocore.client import Config
        except ImportError as e:
            raise PublisherError(
                "S3 publishing requires the [publish] extra. "
                "Install with: pip install qa-dashboard[publish]"
            ) from e

        import boto3

        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._public = bool(public)
        self._endpoint_url = endpoint_url
        kwargs: dict[str, Any] = {}
        if access_key:
            kwargs["aws_access_key_id"] = access_key
        if secret_key:
            kwargs["aws_secret_access_key"] = secret_key
        if region:
            kwargs["region_name"] = region
        if endpoint_url:
            kwargs["endpoint_url"] = endpoint_url
        if force_path_style:
            kwargs["config"] = Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
            )
        self._client = boto3.client("s3", **kwargs)

    def _full_key(self, key: str) -> str:
        if self._prefix:
            return f"{self._prefix}/{key.lstrip('/')}"
        return key.lstrip("/")

    def put(self, key: str, body: bytes, content_type: str) -> None:
        params: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": self._full_key(key),
            "Body": body,
            "ContentType": content_type,
        }
        if self._public:
            params["ACL"] = "public-read"
        try:
            self._client.put_object(**params)
        except Exception as e:  # boto3 errors are many; one wrapping is enough
            raise PublisherError(f"S3 put_object failed for {key}: {e}") from e

    def get(self, key: str) -> bytes | None:
        try:
            resp = self._client.get_object(Bucket=self._bucket, Key=self._full_key(key))
        except Exception as e:
            # NoSuchKey is the common case; everything else is also "missing"
            # for our read-modify-write semantics, but log noisier errors.
            msg = str(e)
            if "NoSuchKey" not in msg and "404" not in msg:
                _log.debug("S3 get_object miss for %s: %s", key, e)
            return None
        return resp["Body"].read()

    def public_url(self, key: str) -> str | None:
        full = self._full_key(key)
        if self._endpoint_url:
            # Custom endpoint: path-style URL is the safest guess
            base = self._endpoint_url.rstrip("/")
            return f"{base}/{self._bucket}/{full}"
        # Virtual-hosted-style for AWS proper
        return f"https://{self._bucket}.s3.amazonaws.com/{full}"

    def describe(self) -> str:
        target = f"s3://{self._bucket}/{self._prefix}".rstrip("/")
        if self._endpoint_url:
            return f"{target} via {self._endpoint_url}"
        return target


def make_publisher(destination: str, **s3_kwargs: Any) -> Publisher:
    """Parse a destination URL and return the matching Publisher."""
    parsed = urlparse(destination)
    scheme = parsed.scheme.lower()
    if scheme == "file":
        # urlparse on "file:///tmp/x" gives netloc="" path="/tmp/x"
        # On Windows it can give path="/C:/..."; let pathlib handle it.
        path = parsed.path or parsed.netloc
        return FilesystemPublisher(Path(path))
    if scheme == "s3":
        bucket = parsed.netloc
        if not bucket:
            raise PublisherError(f"missing bucket in destination: {destination!r}")
        prefix = parsed.path.lstrip("/")
        return S3Publisher(bucket=bucket, prefix=prefix, **s3_kwargs)
    if not scheme or (len(scheme) == 1 and scheme.isalpha()):
        # No scheme, or a single letter that is a Windows drive letter (e.g. "C:\...").
        return FilesystemPublisher(Path(destination))
    raise PublisherError(f"unsupported destination scheme {scheme!r}; expected s3:// or file://")


# ---------------------------------------------------------------------------
# Walking + content type
# ---------------------------------------------------------------------------


_MIME_OVERRIDES = {
    ".html": "text/html",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".css": "text/css",
    ".js": "application/javascript",
    ".txt": "text/plain",
}


def _content_type_for(path: Path) -> str:
    # Hardcoded overrides first — mimetypes on Windows reads the registry,
    # which may be missing newer types like .webp.
    known = _MIME_OVERRIDES.get(path.suffix.lower())
    if known:
        return known
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _iter_run_files(run_dir: Path) -> Iterable[Path]:
    for p in run_dir.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(run_dir)
        if rel.parts and rel.parts[0] in _SKIP_DIRS:
            continue
        if rel.name in _SKIP_NAMES:
            continue
        yield p


# ---------------------------------------------------------------------------
# Rollup index page
# ---------------------------------------------------------------------------


def _build_rollup_index(entries: list[dict]) -> str:
    """Generate a tiny, self-contained HTML index of recent runs.

    No JS, no external CSS — everything inlined so any static-hosting
    target (S3 website, GitHub Pages, Cloudflare R2 public, plain
    ``python -m http.server``) works without extra config.
    """
    rows: list[str] = []
    for e in entries:
        run_id = html.escape(e.get("run_id", ""))
        status = html.escape(e.get("status", "") or "pass")
        status_class = {
            "pass": "ok",
            "fail": "bad",
            "error": "bad",
            "skip": "warn",
        }.get(status, "ok")
        started = html.escape(e.get("started_at", "") or "")
        duration_ms = int(e.get("duration_ms", 0) or 0)
        if duration_ms < 1000:
            duration = f"{duration_ms} ms"
        elif duration_ms < 60_000:
            duration = f"{duration_ms / 1000:.1f} s"
        else:
            duration = f"{duration_ms / 60_000:.1f} min"
        summary = e.get("summary", {}) or {}
        pass_rate = float(summary.get("pass_rate", 0.0) or 0.0)
        total = int(summary.get("total", 0) or 0)
        passed = int(summary.get("passed", 0) or 0)
        failed = int(summary.get("failed", 0) or 0)
        skipped = int(summary.get("skipped", 0) or 0)
        errors = int(summary.get("error", 0) or 0)
        rows.append(
            f"""<tr onclick="location.href='{run_id}/index.html'">
              <td><span class="badge {status_class}">{status}</span></td>
              <td><a href="{run_id}/index.html"><code>{run_id}</code></a></td>
              <td>{started}</td>
              <td class="num">{duration}</td>
              <td class="num">{round(pass_rate * 100)}%</td>
              <td class="num">{total}</td>
              <td class="num pass">{passed}</td>
              <td class="num fail">{failed}</td>
              <td class="num skip">{skipped}</td>
              <td class="num err">{errors}</td>
            </tr>"""
        )

    body_rows = (
        "\n".join(rows)
        if rows
        else ('<tr><td colspan="10" class="empty">No runs published yet.</td></tr>')
    )
    return _ROLLUP_TEMPLATE.replace("{rows}", body_rows).replace("{count}", str(len(entries)))


_ROLLUP_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>qa-dashboard — recent runs</title>
<style>
  :root {
    --bg:#fafafa; --card:#fff; --text:#0f172a; --muted:#64748b;
    --border:#e2e8f0; --brand:#1d4ed8;
    --ok:#16a34a; --bad:#dc2626; --warn:#ca8a04;
  }
  *{box-sizing:border-box}
  html,body{margin:0;background:var(--bg);color:var(--text);
    font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;}
  a{color:var(--brand);text-decoration:none}
  a:hover{text-decoration:underline}
  .container{max-width:1100px;margin:24px auto;padding:0 24px}
  h1{font-size:22px;margin:0 0 4px;letter-spacing:-0.01em}
  p.sub{margin:0 0 20px;color:var(--muted)}
  .card{background:var(--card);border:1px solid var(--border);
    border-radius:12px;box-shadow:0 1px 2px rgb(0 0 0/.04),0 1px 3px rgb(0 0 0/.06);
    overflow:hidden}
  table{width:100%;border-collapse:collapse}
  th,td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--border);font-size:13px}
  th{color:var(--muted);font-weight:500;text-transform:uppercase;font-size:11px;
    letter-spacing:0.04em;background:#f8fafc}
  tr:hover{background:#f8fafc;cursor:pointer}
  tr:last-child td{border-bottom:0}
  td.num{font-variant-numeric:tabular-nums;text-align:right}
  td.num.pass{color:var(--ok)}
  td.num.fail{color:var(--bad)}
  td.num.skip{color:var(--warn)}
  td.num.err{color:var(--bad)}
  td.empty{text-align:center;color:var(--muted);padding:48px 16px}
  .badge{display:inline-block;padding:2px 8px;border-radius:999px;
    font-size:11px;font-weight:600;letter-spacing:0.02em;text-transform:uppercase}
  .badge.ok{background:#dcfce7;color:var(--ok)}
  .badge.bad{background:#fee2e2;color:var(--bad)}
  .badge.warn{background:#fef9c3;color:var(--warn)}
  footer{color:var(--muted);font-size:12px;text-align:center;margin:24px 0}
  code{font-size:12.5px}
</style>
</head>
<body>
<div class="container">
  <h1>qa-dashboard</h1>
  <p class="sub">{count} recent run(s). Click a row to open the full report.</p>
  <div class="card">
    <table>
      <thead>
        <tr>
          <th>Status</th><th>Run</th><th>Started</th><th class="num">Duration</th>
          <th class="num">Pass</th><th class="num">Total</th>
          <th class="num">P</th><th class="num">F</th><th class="num">S</th><th class="num">E</th>
        </tr>
      </thead>
      <tbody>
        {rows}
      </tbody>
    </table>
  </div>
  <footer>Generated by qa-dashboard publish-static</footer>
</div>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


def publish_static(
    run_dir: Path,
    destination: str,
    *,
    rollup_window: int = 50,
    skip_rollup: bool = False,
    brand_color: str | None = None,
    s3_kwargs: dict | None = None,
) -> PublishResult:
    """Upload ``run_dir`` to ``destination`` and refresh the rollup.

    Returns a :class:`PublishResult` describing what landed where.
    """
    run_dir = Path(run_dir)
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise PublisherError(f"no manifest.json in {run_dir}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    run_id = manifest.get("run_id")
    if not run_id:
        raise PublisherError("manifest is missing run_id")

    # Make sure the HTML report exists (regenerate if missing or if a
    # brand-color override was supplied).
    index_html = run_dir / "index.html"
    if not index_html.exists() or brand_color is not None:
        from .report.generator import generate_index_html

        generate_index_html(run_dir, brand_color=brand_color)

    publisher = make_publisher(destination, **(s3_kwargs or {}))
    _log.info("publish: uploading %s -> %s", run_id, publisher.describe())

    uploaded = 0
    for src in _iter_run_files(run_dir):
        rel = src.relative_to(run_dir).as_posix()
        key = f"{run_id}/{rel}"
        publisher.put(key, src.read_bytes(), _content_type_for(src))
        uploaded += 1

    run_url = publisher.public_url(f"{run_id}/index.html")
    rollup_url: str | None = None

    if not skip_rollup:
        rollup_url = _refresh_rollup(publisher, manifest, rollup_window)

    return PublishResult(
        run_id=run_id,
        destination=publisher.describe(),
        run_url=run_url,
        rollup_url=rollup_url,
        files_uploaded=uploaded,
    )


def _summary_for_rollup(manifest: dict) -> dict:
    s = manifest.get("summary") or {}
    return {
        "run_id": manifest.get("run_id"),
        "status": manifest.get("status"),
        "started_at": manifest.get("started_at"),
        "ended_at": manifest.get("ended_at"),
        "duration_ms": manifest.get("duration_ms", 0),
        "summary": {
            "total": s.get("total", 0),
            "passed": s.get("passed", 0),
            "failed": s.get("failed", 0),
            "skipped": s.get("skipped", 0),
            "error": s.get("error", 0),
            "pass_rate": s.get("pass_rate", 0.0),
        },
    }


def _refresh_rollup(
    publisher: Publisher,
    manifest: dict,
    window: int,
) -> str | None:
    """Read existing runs.json, prepend new entry, trim, rewrite + index.html."""
    existing_bytes = publisher.get("runs.json")
    entries: list[dict] = []
    if existing_bytes:
        try:
            data = json.loads(existing_bytes.decode("utf-8"))
            if isinstance(data, list):
                entries = data
            elif isinstance(data, dict) and isinstance(data.get("runs"), list):
                entries = data["runs"]
        except (UnicodeDecodeError, json.JSONDecodeError):
            _log.warning("publish: existing runs.json was not parseable; rewriting")

    new_entry = _summary_for_rollup(manifest)
    # Deduplicate by run_id — if the same run gets re-published, replace
    # instead of accumulating.
    entries = [e for e in entries if e.get("run_id") != new_entry["run_id"]]
    entries.insert(0, new_entry)
    # Sort by started_at desc as a defensive measure; trim to window.
    entries.sort(key=lambda e: e.get("started_at") or "", reverse=True)
    entries = entries[:window]

    runs_json = json.dumps(
        {"schema_version": 1, "runs": entries}, ensure_ascii=False, indent=2
    ).encode("utf-8")
    publisher.put("runs.json", runs_json, "application/json")

    rollup_html = _build_rollup_index(entries).encode("utf-8")
    publisher.put("index.html", rollup_html, "text/html; charset=utf-8")

    return publisher.public_url("index.html")
