# qa-dashboard examples

Runnable starter projects for each supported integration. Copy the
folder, follow the per-example README, and you'll have a populated
dashboard in a few minutes.

| Example | What it shows |
|---|---|
| [pytest-minimal/](pytest-minimal/) | The smallest possible pytest run. No network, no driver — just the dashboard wiring. |
| [pytest-selenium-bidi/](pytest-selenium-bidi/) | Selenium 4 + Chrome with BiDi/CDP network capture into the unified `flows[]` schema. |
| [playwright-typescript/](playwright-typescript/) | Playwright TS with the native reporter and the opt-in network-capture fixtures. |
| [har-ingest/](har-ingest/) | Ingest a HAR file produced by Chrome DevTools / Playwright `recordHar` / k6 / BrowserMob. |
| [junit-ingest/](junit-ingest/) | Java/Maven Surefire results → qa-dashboard via JUnit XML ingest. |

Each example is self-contained and can be copied into your own project
as a starting point.
