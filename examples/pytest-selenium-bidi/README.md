# pytest + Selenium 4 BiDi/CDP network capture

Run a Selenium 4 + Chrome test under pytest with native network
capture (no mitmproxy, no CA cert install).

## Setup

```bash
pip install qa-dashboard selenium webdriver-manager
```

## Run

```bash
pytest --qa-dashboard-mitm-skip
open captures/run_*/index.html
```

`--qa-dashboard-mitm-skip` is important here: we're using BiDi/CDP for
capture, not mitm. The Network tab in the dashboard will be populated
from `bidi_network_capture(driver)` in `conftest.py`.

## What you'll see

- One test per network exchange with `httpbin.org`.
- Per-test step breakdowns from the `step` fixture.
- Full request/response bodies in the Network tab.
- Default credential redaction applied to `Authorization`, `Cookie`,
  etc. — see [../../SECURITY.md](../../SECURITY.md) to add your own
  patterns via `--qa-dashboard-redact`.
