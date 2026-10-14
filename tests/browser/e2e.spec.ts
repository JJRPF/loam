import { test, expect, openApp, openTab, signIn, BEAR_BROOK_LINK } from './fixtures';
import type { Page } from '@playwright/test';
import fs from 'node:fs';
import { WEB, API, LIMITED_API } from './playwright.config';

async function waitForResults(page: Page) {
  await page.waitForSelector('article', { timeout: 90_000 });
  await page.waitForFunction(() => !document.body.innerText.includes('Calculating distinct candidate'), null, { timeout: 90_000 });
}

test.describe('route planning end to end at Bear Brook State Park (signed in)', () => {
  test('a loop builds, options list, profile and strip render, GPX and FIT download', async ({ page }) => {
    await signIn(page);
    await page.goto(BEAR_BROOK_LINK);
    await waitForResults(page);

    expect(await page.locator('article').count()).toBeGreaterThan(1);
    await expect(page.getByTestId('elevation-profile').first()).toBeVisible();
    await expect(page.getByTestId('surface-strip').first()).toBeVisible();
    // the strip has coloured segments, the profile has a drawn path
    expect(await page.getByTestId('surface-strip').first().locator('div').count()).toBeGreaterThan(1);
    expect(await page.getByTestId('elevation-profile').first().locator('path').count()).toBeGreaterThan(0);

    for (const [button, ext, check] of [
      ['Download GPX', '.gpx', (b: Buffer) => b.toString('utf8', 0, 200).includes('<?xml')],
      ['Download FIT', '.fit', (b: Buffer) => b.toString('latin1', 8, 12) === '.FIT'],
    ] as const) {
      const [download] = await Promise.all([page.waitForEvent('download', { timeout: 60_000 }), page.getByRole('button', { name: button }).click()]);
      expect(download.suggestedFilename().toLowerCase().endsWith(ext)).toBe(true);
      const file = await download.path();
      const bytes = fs.readFileSync(file!);
      expect(bytes.length).toBeGreaterThan(500);
      expect(check(bytes), `${button} content`).toBe(true);
    }
  });

  test('the report modal says the report is a public GitHub issue (nothing is submitted)', async ({ page }) => {
    await signIn(page);
    await page.goto(BEAR_BROOK_LINK);
    await waitForResults(page);
    await page.getByRole('button', { name: 'Report bad route' }).first().click();
    const dialog = page.getByRole('dialog', { name: 'Report bad route' });
    await expect(dialog).toContainText('public issue on GitHub');
    await expect(dialog.getByRole('link', { name: 'Privacy Policy' })).toHaveAttribute('href', '/legal/privacy/#reports');
    await expect(dialog.getByRole('button', { name: 'Submit' }).or(dialog.locator('button.btn-primary'))).toBeDisabled(); // needs a comment first
    await dialog.getByRole('button', { name: 'Cancel' }).click();
    await expect(dialog).toHaveCount(0);
  });

  test('signed-in You panel shows privacy controls and the account actions', async ({ page }) => {
    await signIn(page);
    await expect(page.getByText(/privacy zones?/i).first()).toBeVisible();
    await expect(page.getByRole('link', { name: 'How heat works' }).first()).toHaveAttribute('href', '/legal/privacy/#heat');
    // not an admin: no developer tools link
    await expect(page.getByText(/Developer Tools/i)).toHaveCount(0);
  });
});

test.describe('rate limits show a friendly inline message, not an alert', () => {
  const limited = (retry = 12) => ({
    status: 429, contentType: 'application/json',
    headers: { 'access-control-allow-origin': WEB, 'retry-after': String(retry) },
    body: JSON.stringify({ detail: `You're building routes quickly. Please wait ${retry} seconds and try again.` }),
  });

  test('route building', async ({ page, issues }) => {
    issues.allow(/429|Route options stream error|too many|Failed to load resource/i);
    let dialogs = 0;
    page.on('dialog', (d) => { dialogs++; void d.dismiss(); });
    await page.route(`${API}/api/route/options/stream*`, (r) => r.fulfill(limited()));
    await page.route(`${API}/api/route/options`, (r) => r.fulfill(limited()));
    await page.route(`${API}/api/route`, (r) => r.fulfill(limited()));
    await page.goto(BEAR_BROOK_LINK);
    await expect(page.getByText(/wait 12 seconds/i).first()).toBeVisible({ timeout: 30_000 });
    expect(dialogs).toBe(0);
  });

  test('place search', async ({ page, issues }) => {
    issues.allow(/429|Failed to load resource/i);
    await page.route(`${API}/api/geocode*`, (r) => r.fulfill({
      status: 429, contentType: 'application/json',
      headers: { 'access-control-allow-origin': WEB, 'retry-after': '30' },
      body: JSON.stringify({ detail: 'Too many searches. Please wait 30 seconds.' }),
    }));
    await openApp(page);
    await page.getByPlaceholder(/search trailhead or town/i).fill('Concord');
    await expect(page.getByRole('status').filter({ hasText: /too many searches/i })).toBeVisible({ timeout: 15_000 });
  });
});

test('the real server answers 429 with Retry-After and a readable message once the limit is hit', async ({ request }) => {
  const get = () => request.get(`${LIMITED_API}/api/geocode?q=Bear`, { headers: { Origin: WEB } });
  for (let i = 0; i < 3; i++) expect((await get()).status()).toBe(200);
  const res = await get();
  expect(res.status()).toBe(429);
  expect(Number(res.headers()['retry-after'])).toBeGreaterThan(0);
  expect(res.headers()['access-control-allow-origin']).toBe(WEB); // the browser can read the message
  expect((await res.json()).detail).toMatch(/wait/i);
});

test('offline: the app shell loads and recently viewed routes are listed', async ({ browser }) => {
  const ctx = await browser.newContext({ serviceWorkers: 'allow', viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  await page.goto('/');
  await page.waitForSelector('canvas');
  await page.evaluate(async () => { await navigator.serviceWorker.ready; });
  await page.reload();
  expect(await page.evaluate(() => !!navigator.serviceWorker.controller)).toBe(true);
  await page.goto(BEAR_BROOK_LINK);
  await waitForResults(page); // viewing stores the route
  await page.waitForTimeout(500);
  await ctx.setOffline(true);
  await page.goto('/');
  await page.waitForSelector('canvas', { timeout: 20_000 });
  await expect(page.getByText('Waiting for connection')).toBeVisible();
  await openTab(page, 'Saved');
  await expect(page.getByText('Recently viewed')).toBeVisible();
  await ctx.setOffline(false);
  await ctx.close();
});
