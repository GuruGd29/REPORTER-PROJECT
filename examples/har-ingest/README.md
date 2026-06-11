# HAR ingest example

Take a HAR file from anywhere — Chrome DevTools "Save all as HAR",
Playwright `recordHar`, BrowserMob Proxy, k6 `--summary-export`, JMeter,
Postman, mitmproxy `--set hardump=...`, Insomnia — and render it as a
qa-dashboard report.

## How to produce a HAR

**Chrome DevTools:**
1. Open DevTools → Network tab
2. Right-click a request → Save all as HAR with content
3. Save as `trace.har`

**Playwright (in your test):**
```ts
await context.newPage({ recordHar: { path: 'trace.har', content: 'embed' } });
```

**BrowserMob Proxy (Java/Selenium):**
```java
proxy.newHar("session");
// ... drive the browser ...
Har har = proxy.getHar();
har.writeTo(new File("trace.har"));
```

## Ingest into a qa-dashboard run

```bash
pip install qa-dashboard
qa-dashboard ingest trace.har
open captures/run_*/index.html
```

Format is auto-detected from the `.har` extension. Use
`--format har` to force it explicitly.

A small synthetic HAR you can use to try this:

```bash
qa-dashboard ingest sample.har
```

See [sample.har](sample.har) in this directory.
