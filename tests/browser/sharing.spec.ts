// GH-42: shared route links and friends, in a real browser. Two test users (Auth emulator), a synthetic route at
// a public trailhead, a signed-out context for the public link. Nothing here touches production.
import AxeBuilder from '@axe-core/playwright';
import fs from 'node:fs';
import type { Browser, Page } from '@playwright/test';
import { test, expect, openTab, signIn, BEAR_BROOK, MOBILE_VIEWPORTS } from './fixtures';
import { API } from './playwright.config';

const SECOND_EMAIL = 'friend@example.com';

/** The signed-in user's Firebase ID token, read from the page's own auth storage (the emulator issues it). */
async function idToken(page: Page): Promise<string> {
  return page.evaluate(() => {
    const key = Object.keys(localStorage).find((k) => k.startsWith('firebase:authUser:'));
    if (!key) throw new Error('no signed-in user');
    return JSON.parse(localStorage.getItem(key)!).stsTokenManager.accessToken as string;
  });
}

/** A short out-and-back near the Bear Brook parking area (a public trailhead). */
function route(name: string) {
  const coords = Array.from({ length: 30 }, (_, i) => [BEAR_BROOK.lon + i * 0.0006, BEAR_BROOK.lat + i * 0.0003]);
  return {
    name, sport: 'mtb', distance_miles: 1.2, elevation_gain_ft: 120, elevation_loss_ft: 110, coordinates: coords,
    surface_breakdown: { singletrack: 70, gravel: 30 },
    surface_strip: [
      { start_index: 0, end_index: 20, surface_type: 'singletrack' },
      { start_index: 20, end_index: 29, surface_type: 'gravel' },
    ],
  };
}

async function saveRoute(page: Page, name: string): Promise<string> {
  const res = await fetch(`${API}/api/saved-routes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${await idToken(page)}` },
    body: JSON.stringify(route(name)),
  });
  expect(res.status).toBe(200);
  return (await res.json()).id;
}

async function deleteRoute(page: Page, id: string) {
  await fetch(`${API}/api/saved-routes/${id}`, { method: 'DELETE', headers: { Authorization: `Bearer ${await idToken(page)}` } });
}

async function freshPage(browser: Browser, viewport = { width: 1280, height: 900 }) {
  const ctx = await browser.newContext({ viewport, colorScheme: 'dark' });
  const page = await ctx.newPage();
  const problems: string[] = [];
  page.on('pageerror', (e) => problems.push(String(e.message)));
  page.on('console', (m) => { if (m.type() === 'error' && !/GL Driver|GPU stall|WebGL|40[4]|410|fonts\.googleapis\.com/i.test(m.text())) problems.push(m.text().slice(0, 200)); });
  return { ctx, page, problems };
}

async function openShareDialog(page: Page, routeName: string) {
  await openTab(page, 'Saved');
  await page.getByRole('button', { name: `Share ${routeName}` }).click();
  const dialog = page.getByRole('dialog', { name: /^Share/ });
  await expect(dialog).toBeVisible();
  return dialog;
}

async function axeClean(page: Page, what: string) {
  const res = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
  const bad = res.violations
    .filter((x) => x.impact === 'serious' || x.impact === 'critical')
    .map((x) => `${x.id} (${x.impact}): ${x.nodes.slice(0, 4).map((n) => `${n.target.join(' ')} ${(n.any[0]?.message || n.failureSummary || '').replace(/\s+/g, ' ').slice(0, 160)}`).join(' | ')}`);
  expect(bad, `axe on ${what}`).toEqual([]);
}

async function noHorizontalScroll(page: Page, what: string) {
  const m = await page.evaluate(() => ({ doc: document.documentElement.scrollWidth, inner: window.innerWidth }));
  expect(m.doc, `${what}: page is wider than the viewport`).toBeLessThanOrEqual(m.inner);
}

test.describe('sharing a route by link', () => {
  test.beforeEach(({ issues }) => { issues.allow(/fonts\.googleapis\.com/); issues.allow(/\b404\b/); });

  test('share, open signed out in a fresh context, download GPX, revoke, the link is dead', async ({ page, browser }) => {
    const name = `Share test ${Date.now()}`;
    await signIn(page);
    const routeId = await saveRoute(page, name);
    try {
      await page.reload();
      await page.waitForSelector('canvas', { timeout: 30_000 });
      const dialog = await openShareDialog(page, name);
      await dialog.getByRole('radio', { name: /Anyone with the link/ }).check();
      await dialog.getByRole('button', { name: 'Create link' }).click();
      const link = await dialog.getByLabel('Link', { exact: true }).inputValue();
      expect(link).toMatch(/\/r\/[A-Za-z0-9_-]{43}$/);
      await dialog.getByRole('button', { name: 'Close' }).click();
      await openTab(page, 'Saved');
      await expect(page.getByText('Shared by link')).toBeVisible();

      // a fresh, signed-out browser context
      const { ctx, page: anon, problems } = await freshPage(browser);
      try {
        await anon.goto(link);
        await expect(anon.getByText('This route was shared with you')).toBeVisible();
        await expect(anon.getByRole('heading', { name })).toBeVisible();
        await expect(anon.getByText('Shared by A Loam rider with a link.')).toBeVisible();
        await expect(anon.getByTestId('surface-strip').first()).toBeVisible();
        await expect(anon.locator('canvas').first()).toBeVisible();
        // none of the owner's details are on the page
        const text = await anon.locator('body').innerText();
        expect(text).not.toContain('rider@example.com');

        const [dl] = await Promise.all([anon.waitForEvent('download', { timeout: 30_000 }), anon.getByRole('button', { name: 'Download GPX' }).click()]);
        expect(dl.suggestedFilename().toLowerCase().endsWith('.gpx')).toBe(true);
        const gpx = fs.readFileSync((await dl.path())!, 'utf8');
        expect(gpx).toContain('<?xml');
        expect(gpx).toContain('<trk>');

        await axeClean(anon, 'the shared route page');

        // the planner is not started on a shared page, and the page is not indexable or referrer-leaking
        expect(await anon.locator('meta[name="robots"]').getAttribute('content')).toContain('noindex');
        const apiResp = await fetch(`${API}/api/shared/${link.split('/').pop()}`);
        expect(apiResp.headers.get('x-robots-tag')).toContain('noindex');

        // revoke from the owner's side
        const again = await openShareDialog(page, name);
        await again.getByRole('radio', { name: /Private/ }).check();
        await again.getByRole('button', { name: 'Stop sharing' }).click();
        await expect(again.getByRole('status')).toContainText('private again');
        await again.getByRole('button', { name: 'Close' }).click();

        await anon.reload();
        await expect(anon.getByRole('heading', { name: 'This link no longer works' })).toBeVisible();
        await axeClean(anon, 'the link-no-longer-works page');
        expect(problems, 'anonymous page problems').toEqual([]);
      } finally {
        await ctx.close();
      }
    } finally {
      await deleteRoute(page, routeId);
    }
  });

  test('an unknown token gets the same friendly page', async ({ browser }) => {
    const { ctx, page, problems } = await freshPage(browser);
    try {
      await page.goto('/r/' + 'a'.repeat(43));
      await expect(page.getByRole('heading', { name: 'This link no longer works' })).toBeVisible();
      expect(problems).toEqual([]);
    } finally {
      await ctx.close();
    }
  });

  test('a route that starts inside a privacy zone says so and trims by default', async ({ page }) => {
    const name = `Zone test ${Date.now()}`;
    await signIn(page);
    const token = await idToken(page);
    const zone = await fetch(`${API}/api/privacy/zones`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ name: 'Test zone', lat: BEAR_BROOK.lat, lon: BEAR_BROOK.lon, radius_m: 200 }),
    });
    expect(zone.status).toBe(200);
    const zoneId = (await zone.json()).id;
    const routeId = await saveRoute(page, name);
    try {
      await page.reload();
      await page.waitForSelector('canvas', { timeout: 30_000 });
      const dialog = await openShareDialog(page, name);
      await dialog.getByRole('radio', { name: /My friends/ }).check();
      await expect(dialog.getByRole('note')).toContainText('inside one of your privacy zones');
      const full = dialog.getByLabel(/Share the full route/);
      await expect(full).not.toBeChecked();
      await dialog.getByRole('button', { name: 'Share with friends' }).click();
      await expect(dialog.getByRole('status')).toContainText('left out');
    } finally {
      await fetch(`${API}/api/privacy/zones/${zoneId}`, { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } });
      await deleteRoute(page, routeId);
    }
  });
});

test.describe('friends', () => {
  test.beforeEach(({ issues }) => { issues.allow(/fonts\.googleapis\.com/); issues.allow(/\b40[134]\b/); });

  test('invite, accept, the friend sees the route, unfriend, it is gone; block and unblock', async ({ page, browser }) => {
    const name = `Friends test ${Date.now()}`;
    page.on('dialog', (d) => d.accept());
    await signIn(page);
    const routeId = await saveRoute(page, name);
    const { ctx, page: friend, problems } = await freshPage(browser);
    friend.on('dialog', (d) => d.accept());
    try {
      await signIn(friend, SECOND_EMAIL);

      // A sets a sharing name and makes an invite
      await openTab(page, 'You');
      await page.getByLabel('Name shown with routes you share').fill('Trail Gnome');
      await page.getByRole('button', { name: 'Save', exact: true }).click();
      await expect(page.getByText('Sharing name saved.')).toBeVisible();
      await page.getByRole('button', { name: 'Make an invite link' }).click();
      const invite = await page.getByLabel(/Invite link/).inputValue();
      expect(invite).toMatch(/\/friends\/invite\/[A-Za-z0-9_-]{43}$/);

      // B opens it, signed in: sees who it is from, accepts
      await friend.goto(invite);
      await expect(friend.getByText('Trail Gnome')).toBeVisible();
      await axeClean(friend, 'the invite page');
      await friend.getByRole('button', { name: 'Accept' }).click();
      await expect(friend.getByRole('heading', { name: 'You are now friends' })).toBeVisible();

      // the invite is one-time
      await friend.reload();
      await expect(friend.getByRole('alert')).toBeVisible();

      // A shares the route with friends; B sees it in Saved > Shared with me
      const dialog = await openShareDialog(page, name);
      await dialog.getByRole('radio', { name: /My friends/ }).check();
      await dialog.getByRole('button', { name: 'Share with friends' }).click();
      await expect(dialog.getByRole('status')).toContainText('Shared with your friends');
      await dialog.getByRole('button', { name: 'Close' }).click();

      await friend.goto('/');
      await friend.waitForSelector('canvas', { timeout: 30_000 });
      await openTab(friend, 'Saved');
      const shared = friend.getByRole('region', { name: 'Shared with me' }).or(friend.locator('section[aria-labelledby="shared-with-me"]'));
      await expect(shared).toContainText(name);
      await expect(shared).toContainText('From Trail Gnome');
      await axeClean(friend, 'Saved > Shared with me');
      await friend.getByRole('button', { name: 'Inspect' }).first().click();
      await expect(friend.getByText(name).first()).toBeVisible();

      // A removes the friend: the route is gone for B
      await openTab(page, 'You');
      await expect(page.getByText(/since \d/).first()).toBeVisible(); // the new friend, shown by their own sharing name
      await page.getByRole('button', { name: 'Remove' }).first().click();
      await expect(page.getByText('Friend removed.')).toBeVisible();
      await friend.reload();
      await friend.waitForSelector('canvas', { timeout: 30_000 });
      await openTab(friend, 'Saved');
      await expect(friend.locator('section[aria-labelledby="shared-with-me"]')).toHaveCount(0);

      // befriend again, then block
      await openTab(page, 'You');
      await page.getByRole('button', { name: 'Make an invite link' }).click();
      const again = await page.getByLabel(/Invite link/).inputValue();
      await friend.goto(again);
      await friend.getByRole('button', { name: 'Accept' }).click();
      await expect(friend.getByRole('heading', { name: 'You are now friends' })).toBeVisible();
      await page.getByRole('button', { name: 'Make an invite link' }).click(); // refreshes the lists
      await page.reload();
      await page.waitForSelector('canvas', { timeout: 30_000 });
      await openTab(page, 'You');
      await page.getByRole('button', { name: 'Block' }).first().click();
      await expect(page.getByText('Blocked.')).toBeVisible();
      await expect(page.getByText('Blocked', { exact: true })).toBeVisible();
      await axeClean(page, 'You > friends and sharing');
      await page.getByRole('button', { name: 'Unblock' }).click();
      await expect(page.getByText('Unblocked.')).toBeVisible();

      expect(problems, 'friend page problems').toEqual([]);
    } finally {
      await ctx.close();
      await deleteRoute(page, routeId);
    }
  });
});

test.describe('layout of the new screens', () => {
  test.beforeEach(({ issues }) => { issues.allow(/fonts\.googleapis\.com/); issues.allow(/\b404\b/); });

  for (const v of MOBILE_VIEWPORTS) {
    test(`public pages fit ${v.name} (${v.width}px)`, async ({ browser }) => {
      const { ctx, page } = await freshPage(browser, v);
      try {
        await page.goto('/r/' + 'b'.repeat(43));
        await expect(page.getByRole('heading', { name: 'This link no longer works' })).toBeVisible();
        await noHorizontalScroll(page, 'link gone');
        await page.goto('/friends/invite/' + 'c'.repeat(43));
        await expect(page.getByRole('heading', { name: 'You have been invited to share routes' })).toBeVisible();
        await noHorizontalScroll(page, 'invite');
        for (const b of await page.getByRole('button').all()) {
          const box = await b.boundingBox();
          if (box && box.width > 0) expect(box.height, 'tap target').toBeGreaterThanOrEqual(43.5);
        }
      } finally {
        await ctx.close();
      }
    });

    test(`a shared route fits ${v.name} (${v.width}px): no overlap, no sideways scroll`, async ({ pageAt, browser }) => {
      const name = `Layout test ${Date.now()}`;
      const page = await pageAt(v);
      await signIn(page);
      const routeId = await saveRoute(page, name);
      try {
        await page.reload();
        await page.waitForSelector('canvas', { timeout: 30_000 });
        const dialog = await openShareDialog(page, name);
        await dialog.getByRole('radio', { name: /Anyone with the link/ }).check();
        await dialog.getByRole('button', { name: 'Create link' }).click();
        const link = await dialog.getByLabel('Link', { exact: true }).inputValue();
        const { ctx, page: anon } = await freshPage(browser, v);
        try {
          await anon.goto(link);
          await expect(anon.getByRole('heading', { name })).toBeVisible();
          await noHorizontalScroll(anon, 'shared route');
          const map = await anon.getByRole('region', { name: 'Route map' }).boundingBox();
          const panel = await anon.locator('main').boundingBox();
          expect(map && panel).toBeTruthy();
          const apart = map!.y + map!.height <= panel!.y + 1 || panel!.y + panel!.height <= map!.y + 1
            || map!.x + map!.width <= panel!.x + 1 || panel!.x + panel!.width <= map!.x + 1;
          expect(apart, 'map and panel overlap').toBe(true);
          for (const label of ['Download GPX', 'Download FIT', 'Copy to my routes', 'Plan a route from here']) {
            const box = await anon.getByRole('button', { name: label }).boundingBox();
            expect(box?.height ?? 0, label).toBeGreaterThanOrEqual(43.5);
          }
        } finally {
          await ctx.close();
        }
        // the dialog itself on this viewport
        const db = await dialog.boundingBox();
        expect(db!.x).toBeGreaterThanOrEqual(0);
        expect(db!.x + db!.width).toBeLessThanOrEqual(v.width);
        await axeClean(page, 'the share dialog');
      } finally {
        await deleteRoute(page, routeId);
      }
    });
  }
});
