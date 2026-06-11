// Playwright + qa-dashboard native network capture example.
//
// Importing `test` from qa-dashboard-fixtures.js (instead of
// @playwright/test) enables automatic request/response capture into
// the unified flows[] schema.
//
// eslint-disable-next-line @typescript-eslint/no-var-requires
const { test, expect } = require('../qa-dashboard-fixtures');

test('homepage loads', async ({ page }) => {
  await test.step('Navigate', async () => {
    await page.goto('https://playwright.dev/');
  });

  await test.step('Header visible', async () => {
    await expect(page.locator('h1')).toContainText('Playwright');
  });
});

test('api fetch is captured', async ({ page }) => {
  await test.step('Trigger XHR', async () => {
    await page.goto('https://httpbin.org/json');
  });

  await test.step('Body contains expected key', async () => {
    await expect(page.locator('body')).toContainText('slideshow');
  });
});
