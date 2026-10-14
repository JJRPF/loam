import { spawn, type ChildProcess } from 'node:child_process';
import path from 'node:path';
import { test, expect } from './fixtures';
import { WEB } from './playwright.config';

const SERVER = path.resolve(__dirname, '../../scripts/browser-test-server.sh');
const OLD = 'http://old-origin.localhost';

test.describe('an app opened on an old origin moves to the public origin (client side)', () => {
  test('path, query and hash are kept', async ({ page }) => {
    await page.goto(`${OLD}:5180/?start=43.1,-71.3&mode=loop#frag`);
    await page.waitForURL(`${WEB}/?start=43.1,-71.3&mode=loop#frag`);
    await expect(page.locator('canvas').first()).toBeVisible();
  });

  test('localhost is never redirected', async ({ page }) => {
    await page.goto('http://localhost:5180/');
    await page.waitForSelector('canvas');
    expect(new URL(page.url()).hostname).toBe('localhost');
  });
});

async function startApi(port: number, env: string[]): Promise<ChildProcess> {
  const child = spawn('bash', [SERVER, String(port), ...env], { stdio: 'ignore', detached: true });
  for (let i = 0; i < 60; i++) {
    try { if ((await fetch(`http://127.0.0.1:${port}/health`)).ok) return child; } catch { /* not yet */ }
    await new Promise((r) => setTimeout(r, 500));
  }
  stopApi(child);
  throw new Error(`API on ${port} did not start`);
}
function stopApi(child: ChildProcess) {
  try { process.kill(-child.pid!, 'SIGTERM'); } catch { /* gone */ }
}

test.describe('the Funnel host sends browsers to the new domain', () => {
  test.setTimeout(240_000);

  test('301 for navigations; the kill-switch worker replaces an old installed one', async ({ browser }) => {
    const port = 8092;
    // 1. the old world: the app served on its own origin with its real service worker
    let api = await startApi(port, ['PUBLIC_APP_ORIGIN=', 'CORS_ORIGINS=http://127.0.0.1:5180']);
    const ctx = await browser.newContext({ serviceWorkers: 'allow' });
    const page = await ctx.newPage();
    try {
      await page.goto(`${OLD}:${port}/legal/`); // a static page: no client-side redirect runs here
      await page.evaluate(async () => { await navigator.serviceWorker.register('/sw.js'); await navigator.serviceWorker.ready; });
      const oldScript = await page.evaluate(async () => (await fetch('/sw.js')).text());
      expect(oldScript).toContain('precacheAndRoute');
      expect(await page.evaluate(async () => !!(await navigator.serviceWorker.getRegistration()))).toBe(true);
      stopApi(api);
      await new Promise((r) => setTimeout(r, 1500));

      // 2. the new API config: this host is the Funnel host and PUBLIC_APP_ORIGIN is set
      api = await startApi(port, [`PUBLIC_APP_ORIGIN=${WEB}`, `API_PUBLIC_HOST=old-origin.localhost`, 'CORS_ORIGINS=http://127.0.0.1:5180']);

      // a fresh browser context sees the 301 for a navigation
      const fresh = await browser.newContext({ serviceWorkers: 'block' });
      const p2 = await fresh.newPage();
      const res = await p2.goto(`${OLD}:${port}/legal/privacy/?x=1`);
      const first = res!.request().redirectedFrom();
      expect(first, 'the first response was a redirect').not.toBeNull();
      expect((await first!.response())!.status()).toBe(301);
      expect(p2.url()).toBe(`${WEB}/legal/privacy/?x=1`);
      await fresh.close();
      // API calls on that host are not redirected
      const cfg = await fetch(`http://127.0.0.1:${port}/api/config`, { headers: { host: `old-origin.localhost:${port}` } }).catch(() => null);
      if (cfg) expect(cfg.status).toBe(200);

      // 3. the old page asks for a new sw.js: it gets the kill switch, unregisters and leaves for the new origin
      await page.evaluate(async () => { await (await navigator.serviceWorker.getRegistration())!.update().catch(() => {}); });
      await page.waitForURL(`${WEB}/`, { timeout: 30_000 });
      const left = await ctx.newPage();
      await left.goto(`${OLD}:${port}/api/config`); // an API path is not redirected, so this stays on the old origin
      expect(new URL(left.url()).hostname).toBe('old-origin.localhost');
      expect(await left.evaluate(async () => (await navigator.serviceWorker.getRegistrations()).length)).toBe(0);
    } finally {
      stopApi(api);
      await ctx.close();
    }
  });
});
