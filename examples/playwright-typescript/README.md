# Playwright TS with native reporter + network capture

## Setup

```bash
npm init -y
npm install --save-dev @playwright/test
npx playwright install chromium

pip install qa-dashboard
qa-dashboard scaffold playwright
```

That drops `qa-dashboard-reporter.js` and `qa-dashboard-fixtures.js`
into the project root.

## Wire the reporter

Add to `playwright.config.ts` (or copy [playwright.config.ts](playwright.config.ts)):

```ts
import { defineConfig } from '@playwright/test';

export default defineConfig({
  reporter: [
    ['list'],
    ['./qa-dashboard-reporter.js', { outputDir: 'captures' }],
  ],
  use: {
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
});
```

## Get native network capture

Import `test` and `expect` from the fixtures file instead of
`@playwright/test`:

```ts
// Before: import { test, expect } from '@playwright/test';
// After:
const { test, expect } = require('./qa-dashboard-fixtures');
```

That's the only change needed. Every test now records its full
network trace into the unified `flows[]` schema with default
credential redaction applied.

## Run

```bash
npx playwright test
qa-dashboard captures/run_*
open captures/run_*/index.html
```
