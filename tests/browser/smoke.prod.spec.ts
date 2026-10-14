import { test, expect } from '@playwright/test';

const BASE = process.env.BASE_URL || 'https://loam.thepfisters.com';
const API = process.env.API_URL || 'https://core-node.tailcd5892.ts.net';
const BEAR_BROOK = '/?sport=mtb&start=43.134855,-71.36592&sn=Bear%20Brook%20State%20Park%20parking&mode=loop&mi=10&terrain=60,20,10,10';

test('the site loads, the map renders, no console, network or CSP errors', async ({ page }) => {
  const problems: string[] = [];
  await page.addInitScript(() => {
    (window as any).__csp = [];
    document.addEventListener('securitypolicyviolation', (e) => (window as any).__csp.push(`${e.violatedDirective} ${e.blockedURI}`));
  });
  page.on('console', (m) => { if (m.type() === 'error' && !/GL Driver|GPU stall/.test(m.text())) problems.push(`console: ${m.text().slice(0, 200)}`); });
  page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`));
  page.on('response', (r) => { if (r.status() >= 400) problems.push(`${r.status()} ${r.url().slice(0, 120)}`); });
  await page.goto('/');
  await page.waitForSelector('canvas', { timeout: 30_000 });
  await page.waitForTimeout(3000);
  problems.push(...(await page.evaluate(() => (window as any).__csp as string[])).map((c) => `csp: ${c}`));
  expect(problems).toEqual([]);
  await expect(page).toHaveTitle(/Loam/);
});

test('legal pages and crawl files answer 200', async ({ request }) => {
  for (const p of ['/legal/', '/legal/privacy/', '/legal/terms/', '/legal/attributions/', '/robots.txt', '/sitemap.xml', '/manifest.json']) {
    expect((await request.get(p)).status(), p).toBe(200);
  }
});

test('the API is reachable cross-origin with the launch settings', async ({ request }) => {
  const res = await request.get(`${API}/api/config`, { headers: { Origin: BASE } });
  expect(res.status()).toBe(200);
  expect(res.headers()['access-control-allow-origin']).toBe(BASE);
  const cfg = await res.json();
  expect(cfg.midpoints_enabled).toBe(false);
  expect(cfg.min_unique_riders).toBe(3);
  expect((await request.get(`${API}/health`)).status()).toBe(200);
});

test('the old Funnel origin sends navigations to the new domain', async ({ request }) => {
  const res = await request.get(`${API}/legal/privacy/?x=1`, { maxRedirects: 0 });
  expect(res.status()).toBe(301);
  expect(res.headers()['location']).toBe(`${BASE}/legal/privacy/?x=1`);
  const sw = await request.get(`${API}/sw.js`, { maxRedirects: 0 });
  expect(sw.status()).toBe(200);
  expect(await sw.text()).toContain('registration.unregister()');
  expect(sw.headers()['cache-control']).toBe('no-store');
});

test('an anonymous route request at Bear Brook succeeds (read-only)', async ({ page }) => {
  await page.goto(BEAR_BROOK);
  const signIn = page.getByText(/sign in to (build|plan)/i);
  await Promise.race([
    page.waitForSelector('article', { timeout: 100_000 }),
    signIn.waitFor({ timeout: 100_000 }),
  ]);
  if (await signIn.count()) test.info().annotations.push({ type: 'note', description: 'anonymous routing needs sign-in; stopped at the prompt' });
  else expect(await page.locator('article').count()).toBeGreaterThan(0);
});
