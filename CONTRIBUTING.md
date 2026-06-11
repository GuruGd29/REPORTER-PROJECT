# Contributing to qa-dashboard

Thanks for your interest in helping out. This document gets you from
zero to a passing PR in about ten minutes.

## Development setup

```bash
git clone https://github.com/your-org/qa-dashboard.git
cd qa-dashboard
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,all,mitm]"
```

The `[dev]` extra pulls in pytest, ruff, mypy, coverage. `[mitm]` adds
mitmproxy; skip it if you only touch ingest/report code.

## Run the checks locally

```bash
ruff check .              # lint
ruff format --check .     # formatting
mypy                      # type-check public API surface (see [tool.mypy] in pyproject.toml)
pytest --cov=qa_dashboard --cov-fail-under=55 --qa-dashboard-mitm-skip
```

CI runs the same matrix on every PR across Python 3.10/3.11/3.12/3.13
and Ubuntu/macOS/Windows.

## What we look for in a PR

1. **Tests for new code.** Unit tests for new modules, end-to-end
   coverage for new CLI commands or pytest options.
2. **No silent failures.** Use the existing logger
   (`logging.getLogger("qa_dashboard.<area>")`). Don't swallow
   exceptions without a `_log.warning(...)` or `_log.exception(...)`
   call.
3. **Public API additions get a `__all__` entry** and a CHANGELOG
   line under `[Unreleased]`.
4. **Schema changes get explicit treatment.** If you touch
   `manifest.json` or `tests/*.json` shape, update
   `bundle/schemas.py`, bump `SCHEMA_VERSION` if it's a break, and
   call it out in the CHANGELOG under **BREAKING**.
5. **Cross-platform safety.** Use `pathlib`, avoid shell-specific
   syntax, prefer `subprocess.run([...])` over `shell=True`.

## Architecture sketch

- [src/qa_dashboard/pytest_plugin.py](src/qa_dashboard/pytest_plugin.py)
  — entry point for the pytest integration. Owns the run lifecycle.
- [src/qa_dashboard/capture/](src/qa_dashboard/capture/) — mitmproxy
  manager + addon that runs in the mitmdump subprocess.
- [src/qa_dashboard/ingest/](src/qa_dashboard/ingest/) — JUnit XML and
  HAR file ingestors.
- [src/qa_dashboard/integrations/](src/qa_dashboard/integrations/) —
  per-framework adapters (Playwright, WebdriverIO, Selenium).
- [src/qa_dashboard/bundle/](src/qa_dashboard/bundle/) — the unified
  on-disk data contract (schema + builder).
- [src/qa_dashboard/report/](src/qa_dashboard/report/) — HTML
  rendering and multi-format export.

The on-disk format is the integration boundary. Anything that produces
a valid `manifest.json` + `tests/*.json` flows through the same
rendering pipeline.

## Releasing

Maintainers only:

```bash
# bump version in pyproject.toml, src/qa_dashboard/__init__.py, JS reporters
# move [Unreleased] entries under a new heading in CHANGELOG.md
git tag vX.Y.Z
git push origin vX.Y.Z
```

The `publish.yml` workflow builds and publishes to PyPI via Trusted
Publishing (OIDC, no token in CI). GitHub creates the release
automatically.

## Reporting bugs / asking for features

Open a GitHub issue with:
- qa-dashboard version (`qa-dashboard --version`)
- Python version, OS
- A minimal reproduction (a 10-line pytest test is usually enough)
- The full traceback or, for capture issues, the contents of
  `<run-dir>/_flows/_addon_errors.log`
