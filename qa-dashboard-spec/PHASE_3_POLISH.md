# Phase 3 — Polish, scale, edge cases

**Goal:** Take the working dashboard from Phase 2 and harden it for
daily use across multiple projects.

**Prerequisite:** Phase 2 verified. Working end-to-end on at least one
real project.

**Estimated size:** 1 PR. Mostly CSS, JS, edge-case handling, and
small Python.

---

## Task checklist

### Task 3.1 — Timeline interactivity

In the per-test view's Timeline tab:

- Hover any step rect → tooltip with name, duration, status
- Hover any API bar → tooltip with method, status, URL (truncated)
- Hover any screenshot dot → tooltip with label
- Click step rect → switch to Test steps tab, select that step (update
  hash)
- Click API bar → switch to Network tab, expand that flow (update hash)
- Click screenshot dot → open lightbox at that screenshot

The tooltip is one floating `<div>` reused across all hovers. No
tooltip library.

Also: re-render the timeline SVG client-side from `record.steps` and
`record.flows` (not static SVG from template). This makes positions
match data automatically.

### Task 3.2 — Console log filtering

Above the console output, add level pill toggles:

```
[DEBUG] [INFO ✓] [WARN ✓] [ERROR ✓]
```

Default: INFO/WARN/ERROR shown, DEBUG hidden. Click to toggle. Use
data attributes + CSS:

```css
.console[data-show-debug="false"] .line[data-level="DEBUG"] { display: none; }
```

Persist toggle state across tab switches but not across page reloads.

### Task 3.3 — Screenshot lightbox

Full-screen overlay:

- `position: fixed; inset: 0;`
- Semi-transparent dark backdrop
- Image centered, `max-width: 90vw; max-height: 90vh`
- Close button top-right, ESC key, backdrop click all close
- Left/right arrow keys + clickable arrows navigate between
  screenshots in capture order
- Show label below the image
- Show step context: "Step 7 · t001_test_login_smoke"

Lightbox can be triggered from:

- Step detail screenshot strip
- Screenshots tab grid
- Timeline dot click

### Task 3.4 — Print stylesheet

Add `@media print` block:

```css
@media print {
  :root { color-scheme: light; }
  .tabs, .net-toolbar, .step-filter, .header-actions { display: none; }
  .panel { display: block !important; }
  .card, .step, .env-card { break-inside: avoid; }
  * { transition: none !important; }
}
```

In suite view print, show only the test list + summary, no test
detail. In test view print, expand all tabs into a long scroll.

Verify by `Cmd+P` and inspecting the preview.

### Task 3.5 — Keyboard accessibility

- Tab navigation through tabs: arrow keys cycle
- Step list rows focusable, Enter to select
- Network rows focusable, Enter to expand
- Test list rows in suite view focusable, Enter to open
- ARIA roles: `role="tab"`, `role="tablist"`, `role="tabpanel"`,
  `aria-selected`, `aria-controls`
- Focus rings visible (`outline: 2px solid var(--info);` on focus)

Use the WAVE Chrome extension or axe DevTools to verify before
declaring done.

### Task 3.6 — Edge cases

Handle these gracefully:

- **Test with zero steps**: Steps tab shows "No steps recorded for
  this test." Other tabs work normally.
- **Test with zero flows**: Network tab shows "No network activity
  captured."
- **Run with zero tests**: Suite view shows "No tests collected by
  pytest. Check test discovery."
- **Manifest with `status: "in_progress"`**: Show a banner: "Run in
  progress — last update X seconds ago."
- **Very long traceback**: Truncate to first 5 + last 5 lines, with
  "show full" toggle. Keep full in DOM so search works.
- **Very long URL**: Ellipsize in table; show full on hover (`title`)
  and in expanded row.
- **TestRecord schema_version mismatch**: Show an error message in
  the test view: "This test record uses schema v2; this viewer
  supports v1. Regenerate via `qa-dashboard <run-dir>`."
- **Missing screenshot file**: If a TestRecord references an asset
  path but the file is missing, show a placeholder + warning.
- **Parametrized tests**: Show parameters in the test header (e.g.
  `[user_type=premium, plan=annual]`).

### Task 3.7 — Pillow-based screenshot downscaling

When `--qa-dashboard-screenshot-max-width=1080` is set (default off):

- If screenshot's natural width > 1080, downscale to 1080 maintaining
  aspect ratio before writing.
- Adds `Pillow` as an optional dependency (`pip install
  qa-dashboard[imaging]`).
- Plugin imports Pillow only when downscaling is requested. If the
  option is set but Pillow isn't installed, error clearly at session
  start.

### Task 3.8 — Per-test standalone rendering

Extend CLI:

```bash
qa-dashboard <run-dir> --test t001_test_login_smoke
```

Renders just that one test as a standalone HTML file at
`<run-dir>/standalone/t001_test_login_smoke.html`. Inlines the
referenced screenshots as base64 data URIs (because the file is meant
to be shared individually).

Useful for: "send me just the failed test report" → one HTML file,
no directory.

### Task 3.9 — Brand color customization

Allow a project to set a brand accent color via pytest option:

```ini
[pytest]
addopts = --qa-dashboard-brand-color=#1d4ed8
```

The HTML template embeds this as `--brand: <color>` and the CSS uses
it for the active tab underline, the suite status badge background,
and the failed-test left border.

If not set, default to the existing palette.

### Task 3.10 — Documentation

Write `qa-dashboard/README.md` (PyPI front page) covering:

- One-paragraph what-this-is
- Quickstart: `pip install qa-dashboard`, add to `pytest.ini`,
  `pytest tests/`, open `index.html`
- The three integration tiers from `PACKAGING.md`
- Link to full docs (`docs/` directory or a separate site)

Write `qa-dashboard/docs/`:

- `getting_started.md` — same as README quickstart but more detail
- `configuration.md` — all the `--qa-dashboard-*` options
- `extending.md` — how to add tags, attach files, set device metadata
- `troubleshooting.md` — common issues (mitmproxy port conflict,
  cert pinning, missing flows)

Keep each doc short. Better to have five 100-line docs than one
500-line doc.

### Task 3.11 — Migration path from legacy `mitm_report.py`

Add a migration section to `troubleshooting.md` covering:

- Running both side-by-side
- When to retire `mitm_report.py`
- Port conflict resolution

### Task 3.12 — Release prep

- CHANGELOG.md — Phase 1 + Phase 2 + Phase 3 changes summarized
- Tag 0.1.0
- Build wheel and sdist: `python -m build`
- Test install in a fresh venv
- Publish to TestPyPI first
- Smoke test from TestPyPI install
- Publish to PyPI

---

## Acceptance criteria

1. All Phase 2 acceptance criteria still pass
2. Timeline tooltips and click-to-jump work
3. Console filter pills work
4. Lightbox is keyboard-navigable
5. Print produces a readable PDF
6. Tab keyboard navigation works
7. All edge cases handled with clear messages, no broken renders
8. `--qa-dashboard-screenshot-max-width=1080` downscales correctly
9. `qa-dashboard <dir> --test <id>` produces standalone HTML
10. Brand color customization works
11. Documentation exists and is sufficient for a new project to
    adopt the package without external help
12. Package is installable from PyPI (or TestPyPI for early dogfood)

---

## Questions to ask before starting Phase 3

1. Approve publishing to PyPI under the name `qa-dashboard`? (If the
   name is taken, alternatives.)
2. License confirmation — MIT?
3. Should the standalone per-test HTML be a built-in feature or a
   separate `qa-dashboard-export` CLI?
4. Want a Slack/Teams notification integration in this phase or as a
   future addon? (Default: future.)
5. Are there company-specific accessibility requirements beyond
   WCAG AA?
