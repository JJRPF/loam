import { test as base, expect, type Page, type BrowserContext } from '@playwright/test';
import { WEB, EMULATOR } from './playwright.config';

export { expect };

export const MOBILE_VIEWPORTS = [
  { name: 'mobile-360', width: 360, height: 740 },
  { name: 'mobile-390', width: 390, height: 844 },
  { name: 'mobile-412', width: 412, height: 915 },
];
export const DESKTOP_VIEWPORTS = [
  { name: 'tablet-768', width: 768, height: 1024 },
  { name: 'desktop-1280', width: 1280, height: 900 },
  { name: 'desktop-1440', width: 1440, height: 900 },
];
export const ALL_VIEWPORTS = [...MOBILE_VIEWPORTS, ...DESKTOP_VIEWPORTS];
export const isMobile = (v: { width: number }) => v.width < 800;

/** Bear Brook State Park, Allenstown NH: the main parking area (a public trail network, used by Round 7 and 8). */
export const BEAR_BROOK = { lat: 43.134855, lon: -71.36592, name: 'Bear Brook State Park parking' };
/** A shared search link: opening it runs the search (10 mile loop, mountain bike). */
export const BEAR_BROOK_LINK =
  `/?sport=mtb&start=${BEAR_BROOK.lat},${BEAR_BROOK.lon}&sn=${encodeURIComponent(BEAR_BROOK.name)}&mode=loop&mi=10&terrain=60,20,10,10`;

// Console noise that is not an app problem: the software GL renderer's performance hints.
const IGNORED_CONSOLE = [/GL Driver Message/i, /GPU stall/i, /WebGL.*(swiftshader|software)/i];

export interface Issues {
  console: string[];
  pageErrors: string[];
  failedRequests: string[];
  csp: string[];
  /** Drop recorded issues whose text matches (for a test that provokes a failure on purpose). */
  allow(pattern: RegExp): void;
}

/** Records console errors, page errors, failed or 4xx/5xx requests and CSP violations on a page. */
async function attachWatch(page: Page, issues: Issues) {
  await page.addInitScript(() => {
    (window as any).__csp = [];
    document.addEventListener('securitypolicyviolation', (e) => {
      (window as any).__csp.push(`${e.violatedDirective} blocked ${e.blockedURI}`);
    });
  });
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    const t = m.text();
    if (IGNORED_CONSOLE.some((r) => r.test(t))) return;
    issues.console.push(t.slice(0, 300));
  });
  page.on('pageerror', (e) => issues.pageErrors.push(String(e.message).slice(0, 300)));
  page.on('requestfailed', (r) => {
    const f = r.failure()?.errorText || '';
    if (/ERR_ABORTED|cancelled/i.test(f)) return; // navigations and superseded fetches
    issues.failedRequests.push(`${r.method()} ${r.url().slice(0, 160)} ${f}`);
  });
  page.on('response', (r) => {
    if (r.status() >= 400) issues.failedRequests.push(`${r.status()} ${r.request().method()} ${r.url().slice(0, 160)}`);
  });
}

/**
 * Every test fails on a console error, an uncaught page error, a failed or 4xx/5xx request, or a CSP violation
 * unless it opts out with issues.allow(). That is the "no console errors, no failed requests, no CSP errors" check.
 * `pageAt(viewport)` opens a page at a viewport (touch emulation below 800 px) under the same watcher.
 */
export const test = base.extend<{ issues: Issues; pageAt: (v: { width: number; height: number }) => Promise<Page> }>({
  issues: [
    async ({}, use) => {
      const allowed: RegExp[] = [];
      const issues: Issues & { pages: Page[] } = {
        console: [], pageErrors: [], failedRequests: [], csp: [], pages: [],
        allow: (p) => { allowed.push(p); },
      };
      await use(issues);
      for (const page of issues.pages) {
        try { issues.csp.push(...(await page.evaluate(() => (window as any).__csp || []))); } catch { /* page already closed */ }
      }
      const keep = (list: string[]) => list.filter((t) => !allowed.some((p) => p.test(t)));
      expect.soft(keep(issues.csp), 'CSP violations').toEqual([]);
      expect.soft(keep(issues.pageErrors), 'uncaught page errors').toEqual([]);
      expect.soft(keep(issues.console), 'console errors').toEqual([]);
      expect.soft(keep(issues.failedRequests), 'failed requests').toEqual([]);
    },
    { auto: true },
  ],
  page: async ({ page, issues }, use) => {
    await attachWatch(page, issues);
    (issues as any).pages.push(page);
    await use(page);
  },
  pageAt: async ({ browser, issues }, use) => {
    const contexts: BrowserContext[] = [];
    await use(async (v) => {
      const mobile = isMobile(v);
      const ctx = await browser.newContext({ viewport: { width: v.width, height: v.height }, isMobile: mobile, hasTouch: mobile, colorScheme: 'dark' });
      contexts.push(ctx);
      const page = await ctx.newPage();
      await attachWatch(page, issues);
      (issues as any).pages.push(page);
      return page;
    });
    for (const c of contexts) await c.close();
  },
});

/** Opens the app and waits until the map has rendered. */
export async function openApp(page: Page, path = '/') {
  await page.goto(path);
  await page.waitForSelector('canvas', { timeout: 30_000 });
  await page.waitForFunction(() => !!document.querySelector('canvas'));
}

export async function openTab(page: Page, name: 'Plan' | 'Route' | 'Explore' | 'Saved' | 'You') {
  await page.getByRole('button', { name, exact: true }).first().click();
}

/** The test account. Real emulator sign-in through the app's own email-link flow; no real address or token. */
export const TEST_EMAIL = 'rider@example.com';

export async function signIn(page: Page, email = TEST_EMAIL) {
  await openApp(page);
  await openTab(page, 'You');
  await page.getByLabel('Email', { exact: true }).fill(email);
  await page.getByRole('button', { name: /email me a sign-in link/i }).click();
  await page.getByText(/check your inbox/i).waitFor();
  const res = await fetch(`${EMULATOR}/emulator/v1/projects/demo-loam/oobCodes`);
  const codes = (await res.json()).oobCodes as { email: string; oobCode: string; requestType: string }[];
  const mine = codes.filter((c) => c.email === email && c.requestType === 'EMAIL_SIGNIN').pop();
  if (!mine) throw new Error('the emulator holds no sign-in code for ' + email);
  await page.goto(`${WEB}/auth/finish?apiKey=fake-api-key&oobCode=${mine.oobCode}&mode=signIn&lang=en`);
  await page.waitForSelector('canvas', { timeout: 30_000 });
  await openTab(page, 'You');
  await expect(page.getByText(email).first()).toBeVisible();
}

export async function clearEmulatorUsers() {
  await fetch(`${EMULATOR}/emulator/v1/projects/demo-loam/accounts`, { method: 'DELETE' });
}

export interface Box { x: number; y: number; width: number; height: number }
export const overlaps = (a: Box, b: Box) =>
  a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;

export async function visibleBox(page: Page, selector: string): Promise<Box | null> {
  return page.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    if (r.width === 0 || r.height === 0 || cs.visibility === 'hidden' || cs.display === 'none') return null;
    return { x: r.x, y: r.y, width: r.width, height: r.height };
  }, selector);
}
