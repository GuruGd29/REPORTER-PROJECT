# Data Contracts

Every schema the system produces or consumes. Refer back constantly.
Field changes require a major version bump and user approval.

All timestamps are ISO 8601 UTC strings with `Z` suffix. All durations
are integer milliseconds. All IDs are strings unless explicitly int.

---

## 1. `manifest.json` — Run-level overview

One per run directory, at the top level. Read first by `index.html`.

```json
{
  "schema_version": 1,
  "run_id": "run_20260522_123456_a3f91c",
  "started_at": "2026-05-22T12:34:56Z",
  "ended_at": "2026-05-22T12:42:18Z",
  "duration_ms": 442000,
  "status": "fail",
  "summary": {
    "total": 47,
    "passed": 42,
    "failed": 3,
    "skipped": 2,
    "error": 0,
    "xfailed": 0,
    "xpassed": 0,
    "pass_rate": 0.894
  },
  "environment": {
    "pytest": "8.2.0",
    "python": "3.12.3",
    "platform": "Linux-6.5.0-x86_64",
    "mitmproxy": "11.0.2",
    "qa_dashboard": "0.1.0",
    "hostname": "ci-runner-04",
    "user": "jenkins",
    "cwd": "/var/jenkins/workspace/hotstar-android"
  },
  "source": {
    "repo": "hotstar-qa-android",
    "branch": "main",
    "commit": "a3f91c2",
    "commit_message": "Add subtitle toggle tests",
    "trigger": "ci_push"
  },
  "config": {
    "mitm_port": 8080,
    "host_filter": "hotstar",
    "screenshot_on_fail": true,
    "command_line": "pytest tests/ -v --tb=short"
  },
  "tests": [
    {
      "test_id": "t001_tests_test_login_smoke",
      "nodeid": "tests/Android_phase2_test.py::test_login_smoke",
      "name": "test_login_smoke",
      "file": "tests/Android_phase2_test.py",
      "status": "fail",
      "started_at": "2026-05-22T12:34:58Z",
      "duration_ms": 107000,
      "step_count": 14,
      "flow_count": 187,
      "screenshot_count": 28,
      "tags": ["smoke", "auth"],
      "error_summary": "AssertionError: expected player state=PLAYING"
    }
  ]
}
```

### Field reference

| Field | Type | Required | Notes |
|---|---|---|---|
| `schema_version` | int | yes | Increment on breaking changes |
| `run_id` | string | yes | Globally unique; matches dir name |
| `started_at` | string (ISO) | yes | session start |
| `ended_at` | string (ISO) \| null | yes | null while in progress |
| `duration_ms` | int \| null | yes | null while in progress |
| `status` | enum | yes | `"pass"`, `"fail"`, `"error"`, `"in_progress"` |
| `summary.total` | int | yes | sum of all categories |
| `summary.passed/failed/skipped/error` | int | yes | pytest outcomes |
| `summary.xfailed/xpassed` | int | yes | expected-fail outcomes |
| `summary.pass_rate` | float | yes | `passed / total`, 3 decimal places |
| `environment.*` | object | yes | best-effort; missing values become `null` |
| `source.*` | object | yes | derived from env vars + `git rev-parse`; nulls allowed |
| `config.*` | object | yes | snapshot of plugin options used |
| `tests` | array | yes | summary entry per test, in execution order |
| `tests[].error_summary` | string \| null | yes | first line of error, null if not failed |

### `status` rules
- `"in_progress"` only while pytest is still running
- `"pass"` if `failed + error == 0`
- `"fail"` if `failed > 0` and `error == 0`
- `"error"` if `error > 0` (setup/teardown errors, not test assertions)

---

## 2. `tests/<test_id>.json` — Per-test record (TestRecord)

One per test executed. Read on demand when user clicks a test.

```json
{
  "schema_version": 1,
  "test_id": "t001_tests_test_login_smoke",
  "nodeid": "tests/Android_phase2_test.py::test_login_smoke",
  "name": "test_login_smoke",
  "file": "tests/Android_phase2_test.py",
  "line": 42,
  "status": "fail",
  "started_at": "2026-05-22T12:34:58Z",
  "ended_at": "2026-05-22T12:36:45Z",
  "duration_ms": 107000,
  "tags": ["smoke", "auth"],
  "parameters": null,
  "outcome": {
    "phase": "call",
    "longrepr": "AssertionError: expected player state=PLAYING, got state=ERROR\n  File ...",
    "traceback_summary": "AssertionError at tests/Android_phase2_test.py:87",
    "stdout_tail": "",
    "stderr_tail": ""
  },
  "steps": [
    { /* Step dict — see section 3 */ }
  ],
  "flows": [
    { /* Flow dict — see section 4 */ }
  ],
  "screenshots": [
    { /* Screenshot record — see section 5 */ }
  ],
  "console": [
    { /* Console line — see section 6 */ }
  ],
  "device": {
    "platform": "Android",
    "platform_version": "14",
    "model": "Pixel 7 emulator",
    "api_level": 34,
    "locale": "en_IN"
  },
  "app": {
    "package": "in.startv.hotstar",
    "version": "24.05.15.3"
  }
}
```

### Field reference

| Field | Type | Notes |
|---|---|---|
| `test_id` | string | matches the filename stem |
| `nodeid` | string | pytest's canonical test identifier |
| `name` | string | `request.node.name` |
| `file` | string | repo-relative path |
| `line` | int \| null | function definition line number |
| `status` | enum | `"pass"`, `"fail"`, `"skip"`, `"error"`, `"xfailed"`, `"xpassed"` |
| `tags` | array of string | from pytest markers; only string-valued markers |
| `parameters` | object \| null | for parametrized tests, the parameter dict |
| `outcome.phase` | enum | `"setup"`, `"call"`, `"teardown"` — where the failure happened |
| `outcome.longrepr` | string \| null | full pytest longrepr if failed |
| `outcome.traceback_summary` | string \| null | one-line summary |
| `device`, `app` | object \| null | populated if test attached them via fixture; null otherwise |

### Note on `parameters`
For `@pytest.mark.parametrize("user_type,plan", [...])` tests, this
captures the actual parameters bound to *this* test instance. The
plugin uses `request.node.callspec.params` if available. If not
parametrized, this is `null`.

---

## 3. The Step dict (nested in TestRecord)

Same as the original spec, but lives inside a TestRecord, not its own
file.

```json
{
  "id": 7,
  "name": "Start playback",
  "status": "fail",
  "started_at": "2026-05-22T12:35:31.600Z",
  "ended_at": "2026-05-22T12:35:35.000Z",
  "duration_ms": 3400,
  "substeps": [
    { "name": "Tap \"Play\" button", "status": "pass", "duration_ms": 60 },
    { "name": "Wait for player init", "status": "pass", "duration_ms": 1200 },
    { "name": "Fetch playback manifest", "status": "fail", "duration_ms": 2100 },
    { "name": "Assert player state == PLAYING", "status": "fail", "duration_ms": 40 }
  ],
  "screenshot_ids": ["t001_step_7_001", "t001_step_7_002"],
  "flow_ids": [17, 18, 19],
  "error": {
    "type": "AssertionError",
    "message": "expected player state=PLAYING, got state=ERROR",
    "traceback": "Traceback (most recent call last):\n..."
  },
  "skip_reason": null
}
```

### Field reference

| Field | Type | Notes |
|---|---|---|
| `id` | int | 1-indexed, sequential within the test |
| `name` | string | human-readable |
| `status` | enum | `"pass"`, `"fail"`, `"skip"` |
| `substeps` | array | may be empty |
| `screenshot_ids` | array of string | references into the test's `screenshots` array |
| `flow_ids` | array of int | references into the test's `flows` array (computed by bundle builder) |
| `error` | object \| null | non-null only for `"fail"` |
| `skip_reason` | string \| null | non-null only for `"skip"` |

### Substep

```json
{ "name": "Tap \"Play\" button", "status": "pass", "duration_ms": 60 }
```

Status is `pass` or `fail`. No `skip` for substeps.

---

## 4. The Flow dict (nested in TestRecord)

Per-flow capture from mitmproxy. Extended from the existing format
with three new fields (`id`, `path`, `step_id`).

```json
{
  "id": 17,
  "timestamp": "2026-05-22T12:35:31.720Z",
  "method": "GET",
  "url": "https://api.hotstar.com/v2/content/12345/playback",
  "host": "api.hotstar.com",
  "path": "/v2/content/12345/playback",
  "status_code": 429,
  "duration_ms": 1240,
  "step_id": 7,
  "request": {
    "headers": { "authorization": "Bearer jwt.eyJ...", "accept": "application/json" },
    "content_type": "application/json",
    "body_encoding": "empty",
    "body_size_bytes": 0,
    "body": ""
  },
  "response": {
    "headers": { "content-type": "application/json", "retry-after": "1" },
    "content_type": "application/json",
    "body_encoding": "json",
    "body_size_bytes": 142,
    "body": {
      "error": "rate_limited",
      "message": "Too many playback requests",
      "retry_after_sec": 1
    }
  }
}
```

### `body_encoding` discriminator

- `"json"` → `body` is a parsed JSON value
- `"text"` → `body` is a string
- `"base64"` → `body` is a base64 string of raw bytes
- `"empty"` → `body` is `""`
- `"omitted"` → `body` is `null`; the body exceeded the inline size
  budget and was dropped from the JSON. Original size in
  `body_size_bytes`. (New in this version.)

### Body size budget

Bodies larger than 100 KB after JSON encoding are replaced with the
`omitted` encoding. This keeps individual TestRecord JSON files from
ballooning. Original body bytes are not preserved by default in this
phase — they're gone after capture. Phase 3 may add an option to
write them as separate files in `assets/`.

---

## 5. The Screenshot record (nested in TestRecord)

```json
{
  "id": "t001_step_7_001",
  "step_id": 7,
  "captured_at": "2026-05-22T12:35:32.100Z",
  "filename": "t001_step_7_001.png",
  "asset_path": "assets/screenshots/t001_step_7_001.png",
  "width": 1080,
  "height": 2400,
  "size_bytes": 184230,
  "label": "before assertion"
}
```

| Field | Type | Notes |
|---|---|---|
| `id` | string | unique across the whole run |
| `step_id` | int \| null | null if attached outside any step |
| `asset_path` | string | **relative to the run directory** — used by `<img src>` |
| `width`, `height` | int \| null | from PNG header; null if unread |
| `label` | string | optional caption; `""` if not provided |

### Files on disk

```
assets/screenshots/t001_step_7_001.png
assets/screenshots/t001_step_7_001.label    (optional sidecar)
```

The `.label` sidecar is a plain UTF-8 text file containing the caption.
If absent, label is `""`.

---

## 6. The Console line (nested in TestRecord)

```json
{ "ts": "2026-05-22T12:35:32.960Z", "level": "WARN", "logger": "playback", "message": "429 from playback — backing off 1s" }
```

| Field | Type | Notes |
|---|---|---|
| `ts` | string (ISO) | wall clock |
| `level` | enum | `"DEBUG"`, `"INFO"`, `"WARN"`, `"ERROR"`, `"CRITICAL"` |
| `logger` | string | `"root"` for unnamed |
| `message` | string | may contain newlines |

The plugin captures stdlib `logging` output via a handler attached at
test start, removed at test end. `print()` output is NOT captured by
default. Use `--qa-dashboard-capture-prints=true` to enable (future).

---

## 7. The `current.txt` side-channel file

Single file at the root of the run directory.

Format (UTF-8, single line, no trailing newline):

```
<test_id>\t<step_id>
```

Or empty (zero-byte file).

Examples:

```
t001_test_login_smoke	7        (step 7 of t001 active)
t001_test_login_smoke	0        (t001 active, no step)
                                 (empty — no test active)
```

mitm_addon reads on every flow:

```python
def _current(self):
    try:
        line = self._current_file.read_text().strip()
        if not line:
            return None, None
        test_id, step_id = line.split("\t")
        return test_id, int(step_id) if step_id != "0" else None
    except (FileNotFoundError, ValueError):
        return None, None
```

Writes use `os.replace()` for atomicity.

---

## 8. The in-memory RunBundle (suite assembly)

This is NOT written to disk. It's the in-memory representation passed
to `report.generator.generate_index_html()`:

```python
RunBundle = TypedDict("RunBundle", {
    "manifest": dict,    # the manifest.json contents
    "tests": list,       # list of TestRecord (loaded from per-test JSONs)
})
```

The HTML generator iterates `manifest.tests` and reads each
`tests/<test_id>.json` on demand if it needs more than the summary.

For `index.html`, it only needs the manifest. Per-test JSONs are
fetched by the browser at click time.

---

## 9. JSON encoding rules

For all files this project produces:

- 2-space indent if `--qa-dashboard-pretty=true`, otherwise no indent
- UTF-8 always
- `ensure_ascii=False`
- Field order matches the schema in this document (use OrderedDict /
  preserve insertion order, no `sort_keys`)
- Numbers: integer milliseconds for durations, float for `pass_rate`
- Dates: ISO 8601 UTC strings, never numeric timestamps
- `null` for missing optional fields, never omit

```python
json.dumps(obj, ensure_ascii=False, indent=2 if pretty else None)
```

## 10. Schema versioning

`schema_version` is a top-level field on `manifest.json` and each
TestRecord. Currently `1`. Increment on breaking changes (field
renames, type changes, semantic shifts). Additive changes (new
optional fields) do not bump the version.

The HTML report reads `schema_version` and renders a clear error if
it doesn't recognize the version:

> This report was generated by a different version of qa-dashboard.
> Schema version: 2 (this viewer supports: 1).
> Regenerate with `python -m qa_dashboard <dir>`.
