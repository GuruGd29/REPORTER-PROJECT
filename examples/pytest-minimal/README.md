# Minimal pytest example

The smallest possible qa-dashboard run.

```bash
pip install qa-dashboard
pytest --qa-dashboard-mitm-skip
open captures/run_*/index.html
```

That's it. No `conftest.py`, no config. The dashboard captures test
results, console logs, environment metadata, and renders an HTML
report.

To wire mitmproxy capture, install with the extra:

```bash
pip install "qa-dashboard[mitm]"
pytest        # no --qa-dashboard-mitm-skip this time
```

You'll need the mitmproxy CA installed in the test target's trust store
to see HTTPS traffic. See [../../SECURITY.md](../../SECURITY.md).
