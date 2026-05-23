# UI Specification

The dashboard has two view modes accessed in a single-page-app style.

**Suite view** is `index.html`'s default rendering — the list of all
tests with summary stats.

**Test view** is what shows when the user clicks a test from the suite
view. Renders the per-test detail (steps, network, screenshots, logs).

These are NOT separate pages — `index.html` swaps between them
client-side. The URL hash updates: `index.html#t001_test_login_smoke`
for direct linking.

## Layout structure (both views)

```
┌────────────────────────────────────────────────────────────────┐
│  HEADER (always visible)                                       │
│  - Suite status badge, run id, timestamp                       │
│  - "← All tests" link (only visible in test view)              │
│  - Export, Print, Filter buttons                               │
├────────────────────────────────────────────────────────────────┤
│  SUITE METRICS BAR (always visible)                            │
│  - 5–6 metric cards: total, passed, failed, skipped, duration, │
│    flaky (optional)                                            │
├────────────────────────────────────────────────────────────────┤
│  VIEW CONTENT                                                  │
│  - Suite view: test list table                                 │
│  - Test view: tabbed test detail (the existing reference UI)   │
└────────────────────────────────────────────────────────────────┘
```

The header stays the same in both views. The metrics bar stays
visible — even when inside a test, the user sees suite-level numbers.
Only the content area changes.

---

## Suite view

The default landing view. Loaded from `manifest.json`.

### Toolbar above the test list

```
┌─────────────────────────────────────────────────────────────────┐
│  [Filter tests…________________]  Status [All ▾]  Sort [Status ▾] │
└─────────────────────────────────────────────────────────────────┘
```

- **Filter input** — substring match on test name and tags (case-insensitive)
- **Status dropdown** — All / Failed / Passed / Skipped / Error
- **Sort dropdown** — Status (failed first) / Name / Duration / Order

### Test list table

```
┌──────────────────────────────────────────────────────────────────────┐
│ Status  Name                          Duration  Steps  API  Failed  │
├──────────────────────────────────────────────────────────────────────┤
│   ✕    test_login_smoke               1m 47s    14/14  187      1   │
│        AssertionError: expected pl…                                  │
├──────────────────────────────────────────────────────────────────────┤
│   ✓    test_playback_basic            45.2s     8/8    62           │
├──────────────────────────────────────────────────────────────────────┤
│   ✓    test_subtitle_toggle           12.4s     4/4    8            │
├──────────────────────────────────────────────────────────────────────┤
│   —    test_offline_download          —         skipped — not on CI │
└──────────────────────────────────────────────────────────────────────┘
```

### Test row anatomy

Each row:
- Status pill (✓ / ✕ / — / ⚠)
- Test name (clickable; opens test view)
- Below test name: error summary if failed, or skip reason if skipped
- Duration column (right-aligned, monospace)
- Steps column: `passed/total` (e.g. `12/14` for a test with 14 steps,
  12 passed)
- API column: flow count
- Failed steps column: count of failed steps within the test

Click anywhere on the row to open the test view.

### Default sort

Failed → Error → Skipped → Passed, then by execution order within
each group. This is what triage needs: see the failures first.

### Pagination

Show all tests by default if total ≤ 200. Above 200, paginate at 100
per page with a simple "Next / Previous" control. No virtualization
— browsers handle 200 rows fine.

Phase 1 ships without pagination. Add only if scale demands.

### Empty states

- **No tests ran**: "No tests were collected by pytest. Check your
  test discovery configuration."
- **All tests passed**: full list still shown, just no red rows. No
  celebration banner.
- **All tests failed**: full list still shown, no special treatment.
- **Suite still running**: top of page shows "Run in progress — last
  updated <ts>" with a manual refresh button. Auto-refresh is NOT
  implemented in Phase 1.

---

## Test view

Triggered by clicking a test in the suite view. Loaded by `fetch()`ing
`tests/<test_id>.json`.

URL hash updates to `#<test_id>` so the view can be bookmarked /
shared.

### Visual contract

This view matches `REFERENCE_TEST_VIEW.html` exactly. Tabs:

1. **Test steps** — master-detail (left list, right detail pane)
2. **Network** — filterable table with row expansion
3. **Timeline** — stacked SVG of steps, flows, screenshots
4. **Screenshots** — grid of thumbnails with lightbox
5. **Console logs** — filterable JSONL viewer
6. **Environment** — device, app, harness cards

All the behavioural details specified in the original mockup apply.
See the reference HTML and click through it to understand.

### Test header

When in test view, the header gains:

- A "← All tests" link that returns to suite view
- The test name as h1
- The test's status badge
- Test nodeid + duration + tags
- "Previous failed test" and "Next failed test" links if applicable
  (Phase 3)

### Tab interaction

Tabs are accessible via:
- Click
- Left/Right arrow keys
- URL hash: `#<test_id>/network` opens the test on the Network tab.
  This is critical for sharing links from Slack.

---

## Cross-view navigation

The whole dashboard is one HTML file (`index.html`) with two view
states. State transitions:

```
suite view  ─ click test ─►  test view (test_id, current tab)
test view   ─ click "← All tests" or browser back ─►  suite view
test view   ─ change tab ─►  same view, different tab (hash updates)
```

URL hash mirrors the state:
- `index.html` → suite view
- `index.html#test_id` → test view, default tab (Test steps)
- `index.html#test_id/network` → test view, Network tab
- `index.html#test_id/network/flow_17` → test view, Network tab, flow 17 expanded

Browser back/forward should work. Use `history.pushState` and listen
to `popstate`.

---

## Suite-level metrics

The header metrics bar shows:

| Card | Value | Notes |
|---|---|---|
| Total tests | int | from `manifest.summary.total` |
| Passed | int (green) | |
| Failed | int (red) | clicks to filter list to failed |
| Skipped | int (amber) | |
| Duration | string (e.g. `7m 22s`) | total run duration |
| Pass rate | percentage | `pass_rate * 100`, 1 decimal |

The "Failed" card is clickable to filter the test list. The others
are not interactive in Phase 1.

---

## Theming

Same as the original UI spec:

- Light/dark mode via `prefers-color-scheme`
- Warm off-white / warm near-black palette
- System fonts only
- Status colors per the table in the original spec
- No gradients, no shadows, no animations > 150ms

Add for suite view:

- The test list rows use the same row-hover pattern as the step list
  in the test view (subtle background change on hover)
- Failed rows get a subtle left border in `--fail` color
- Skipped rows get reduced opacity (0.7)

---

## Performance budget

Suite view (`index.html`) should load and render in < 200ms for a
typical run (200 tests):

- `index.html` size: < 200 KB (no per-test data embedded)
- `manifest.json` size: typically 50–200 KB for 200 tests
- Initial render: just the test table from the manifest
- Test detail: `fetch()` on click, typical TestRecord 100KB–2MB

If the manifest gets above 1 MB, that's a sign the test count is
beyond medium scale. Defer that problem.

---

## Accessibility

- All interactive elements keyboard-reachable
- Status colors backed by text labels (✓ ✕ — symbols)
- `prefers-reduced-motion` honored
- Focus rings visible
- The lightbox is keyboard-navigable (arrow keys + ESC)
- ARIA roles on tabs and tablists

---

## Print

`Cmd+P` / `Ctrl+P`:

- Force light mode
- Hide tabs, expand all panels (in test view)
- Hide filters, dropdowns, buttons
- In suite view, print the test list with summary; one row per test,
  no test-detail content (too large to print)
- Page breaks between major sections

Phase 3 polish. Phase 2 ships with basic print working but not
beautiful.
