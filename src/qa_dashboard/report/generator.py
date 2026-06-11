from __future__ import annotations

import json
from pathlib import Path
from string import Template

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _safe_color(c: str | None) -> str | None:
    if not c:
        return None
    c = c.strip()
    if not c.startswith("#"):
        return None
    if len(c) not in (4, 7, 9):
        return None
    for ch in c[1:]:
        if ch not in "0123456789abcdefABCDEF":
            return None
    return c


def generate_index_html(run_dir: Path, brand_color: str | None = None) -> Path:
    """Render ``index.html`` from the run directory's manifest + templates.

    Returns the path to the written HTML file.
    """
    run_dir = Path(run_dir)
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"No manifest.json in {run_dir}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    template = (TEMPLATES_DIR / "index.html").read_text(encoding="utf-8")
    styles = (TEMPLATES_DIR / "styles.css").read_text(encoding="utf-8")
    runtime = (TEMPLATES_DIR / "runtime.js").read_text(encoding="utf-8")

    title = f"Run {manifest.get('run_id', '?')} — {manifest.get('status', '?')}"
    brand = _safe_color(brand_color)
    brand_style = f"<style>:root {{ --brand: {brand}; }}</style>" if brand else ""
    brand_js = json.dumps(brand) if brand else "null"

    # Avoid string.Template's $ collisions inside CSS/JS by using safe_substitute
    html = Template(template).safe_substitute(
        title=_html_escape(title),
        styles=styles,
        runtime_js=runtime,
        manifest_json=json.dumps(manifest, ensure_ascii=False),
        brand_style=brand_style,
        brand_color_js=brand_js,
    )
    out = run_dir / "index.html"
    out.write_text(html, encoding="utf-8")
    return out


def generate_standalone_test_html(run_dir: Path, test_id: str) -> Path:
    """Render a single self-contained HTML for one test (Phase 3).

    Screenshots are inlined as base64 data URIs so the file is portable.
    Output goes to ``<run_dir>/standalone/<test_id>.html``.
    """
    import base64

    run_dir = Path(run_dir)
    test_json = run_dir / "tests" / f"{test_id}.json"
    if not test_json.exists():
        raise FileNotFoundError(f"No such test record: {test_json}")
    record = json.loads(test_json.read_text(encoding="utf-8"))

    # Inline screenshots as data URIs
    for sh in record.get("screenshots", []):
        asset = run_dir / sh["asset_path"]
        if asset.exists():
            data = asset.read_bytes()
            b64 = base64.b64encode(data).decode("ascii")
            sh["asset_path"] = f"data:image/png;base64,{b64}"

    # Build a minimal manifest with just this test
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    standalone_manifest = dict(manifest)
    standalone_manifest["tests"] = [
        t for t in manifest.get("tests", []) if t.get("test_id") == test_id
    ]

    template = (TEMPLATES_DIR / "index.html").read_text(encoding="utf-8")
    styles = (TEMPLATES_DIR / "styles.css").read_text(encoding="utf-8")
    runtime = (TEMPLATES_DIR / "runtime.js").read_text(encoding="utf-8")

    # Prepend a small shim so the runtime finds the record without fetch()
    shim = (
        "\n// standalone shim: provide the single test record directly\n"
        "window.__STANDALONE_TEST__ = " + json.dumps(record, ensure_ascii=False) + ";\n"
        "(function () {\n"
        "  const origFetch = window.fetch;\n"
        "  window.fetch = function (url) {\n"
        f"    if (typeof url === 'string' && url.endsWith('{test_id}.json')) {{\n"
        "      return Promise.resolve(new Response(JSON.stringify(window.__STANDALONE_TEST__), {status: 200}));\n"
        "    }\n"
        "    return origFetch.apply(this, arguments);\n"
        "  };\n"
        "  if (!window.location.hash) window.location.hash = " + json.dumps(test_id) + ";\n"
        "})();\n"
    )

    html = Template(template).safe_substitute(
        title=_html_escape(f"Test {test_id}"),
        styles=styles,
        runtime_js=shim + runtime,
        manifest_json=json.dumps(standalone_manifest, ensure_ascii=False),
        brand_style="",
        brand_color_js="null",
    )
    out_dir = run_dir / "standalone"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{test_id}.html"
    out.write_text(html, encoding="utf-8")
    return out


def _html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
