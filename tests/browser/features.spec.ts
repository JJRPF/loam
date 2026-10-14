import { test, expect, openApp, openTab, signIn, BEAR_BROOK_LINK, ALL_VIEWPORTS } from './fixtures';
import type { Page } from '@playwright/test';
import { WEB, API } from './playwright.config';

async function waitForResults(page: Page) {
  await page.waitForSelector('article', { timeout: 90_000 });
  await page.waitForFunction(() => !document.body.innerText.includes('Calculating distinct candidate'), null, { timeout: 90_000 });
}

test.describe('midpoints are off (ENABLE_MIDPOINTS=false)', () => {
  test('the Plan panel has no midpoint UI in any route mode', async ({ page }) => {
    await openApp(page);
    for (const mode of ['Loop / Round Trip', 'Point to Point', 'Out & Back']) {
      await page.getByRole('button', { name: mode }).click();
      await expect(page.getByRole('button', { name: /add midpoint/i })).toHaveCount(0);
      await expect(page.getByText(/midpoint/i)).toHaveCount(0);
    }
  });

  test('a shared link with via= loads without midpoints and says so', async ({ page }) => {
    await page.goto(`${BEAR_BROOK_LINK}&via=43.1400,-71.3500`);
    await waitForResults(page);
    await expect(page.getByText(/midpoints are turned off/i).first()).toBeVisible();
    expect(page.url()).not.toContain('via=');
  });
});

test('there is no water and shops toggle anywhere', async ({ page }) => {
  await openApp(page);
  await expect(page.getByText(/water|shops/i)).toHaveCount(0);
  await openTab(page, 'Explore');
  await openTab(page, 'Saved');
  await openTab(page, 'You');
  await expect(page.getByText(/water & shops|water and shops/i)).toHaveCount(0);
});

test('the signed-out You panel has no preference controls that do nothing', async ({ page }) => {
  await openApp(page);
  await openTab(page, 'You');
  const body = await page.innerText('body');
  for (const t of ['Display Theme', 'Units', 'Endpoint Trimming', 'Privacy Threshold']) expect(body).not.toContain(t);
});

test('the terrain mix dividers move with the keyboard and by dragging', async ({ page }) => {
  await openApp(page);
  const d0 = page.locator('[data-testid="terrain-divider-0"]');
  await d0.waitFor();
  const before = Number(await d0.getAttribute('aria-valuenow'));
  await d0.focus();
  await page.keyboard.press('ArrowLeft');
  await page.keyboard.press('ArrowLeft');
  const afterKey = Number(await d0.getAttribute('aria-valuenow'));
  expect(afterKey).toBe(before - 10);
  const box = (await d0.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 - 60, box.y + box.height / 2, { steps: 5 });
  await page.mouse.up();
  expect(Number(await d0.getAttribute('aria-valuenow'))).toBeLessThan(afterKey);
});

test('"Round N" never appears in the UI and no heat text says it is off', async ({ page }) => {
  await openApp(page);
  for (const t of ['Plan', 'Explore', 'Saved', 'You'] as const) {
    await openTab(page, t);
    const body = await page.innerText('body');
    expect(body).not.toMatch(/Round \d/);
    expect(body).not.toMatch(/temporarily off|turned off for now|heat is off/i);
  }
});

test.describe('heat info text', () => {
  test('explains the rule and the creator\'s seed rides when seed heat is public', async ({ page }) => {
    await openApp(page);
    await page.getByRole('button', { name: 'About heat' }).click();
    const note = page.getByRole('note');
    await expect(note).toContainText('Heat shows trails ridden by 3 or more people in the past year.');
    await expect(note).toContainText("it also includes Loam's creator's own rides on trails");
    expect(await note.innerText()).not.toMatch(/temporarily off/i);
  });

  test('omits the seed sentence when seed heat is not public', async ({ page }) => {
    await page.route(`${API}/api/heat/meta`, (r) => r.fulfill({
      contentType: 'application/json', headers: { 'access-control-allow-origin': WEB },
      body: JSON.stringify({ min_unique_riders: 3, seed_heat_public: false }),
    }));
    await openApp(page);
    await page.getByRole('button', { name: 'About heat' }).click();
    await expect(page.getByRole('note')).toHaveText('Heat shows trails ridden by 3 or more people in the past year.');
  });
});

test.describe('results heading is pluralized', () => {
  test('1 candidate route', async ({ page }) => {
    await page.goto(BEAR_BROOK_LINK.replace('mi=10', 'mi=1'));
    await expect(page.getByText(/^1 candidate route$/)).toBeVisible({ timeout: 90_000 });
  });
  test('N candidate routes', async ({ page }) => {
    await page.goto(BEAR_BROOK_LINK);
    await expect(page.getByText(/^\d+ candidate routes$/)).toBeVisible({ timeout: 90_000 });
    const n = Number((await page.getByText(/^\d+ candidate routes$/).innerText()).split(' ')[0]);
    expect(n).toBeGreaterThan(1);
  });
});

test.describe('connectors follow the server\'s flags (/api/connectors)', () => {
  test('Strava and Trailforks are absent with the flags off (the real server)', async ({ page }) => {
    await signIn(page);
    await openTab(page, 'You');
    await expect(page.getByText(/garmin/i).first()).toBeVisible(); // the connector list has loaded
    const body = await page.innerText('body');
    expect(body).not.toMatch(/strava/i);
    expect(body).not.toMatch(/trailforks/i);
    expect(body).toMatch(/garmin/i);
  });

  test('they appear when the server reports them enabled', async ({ page }) => {
    // the real response, with the two flags switched on (the dev run of the same flags)
    await page.route(`${API}/api/connectors`, async (route) => {
      const res = await route.fetch();
      const list = (await res.json()) as { name: string; enabled: boolean }[];
      for (const c of list) if (c.name === 'strava' || c.name === 'trailforks') c.enabled = true;
      await route.fulfill({ response: res, json: list });
    });
    await signIn(page);
    await openTab(page, 'You');
    await expect(page.getByText(/strava/i).first()).toBeVisible();
    const body = await page.innerText('body');
    expect(body).toMatch(/strava/i);
    expect(body).toMatch(/trailforks/i);
  });
});

test.describe('legal pages', () => {
  const pages = [
    ['/legal/', /legal/i], ['/legal/privacy/', /privacy/i], ['/legal/terms/', /terms/i], ['/legal/attributions/', /attributions?/i],
  ] as const;

  for (const [path, heading] of pages) {
    test(`${path} loads cold, with no service worker`, async ({ browser }) => {
      const ctx = await browser.newContext({ serviceWorkers: 'block' });
      const page = await ctx.newPage();
      const res = await page.goto(path);
      expect(res!.status()).toBe(200);
      await expect(page.locator('h1').first()).toHaveText(heading);
      await ctx.close();
    });
  }

  test('the footer links open the pages and Source code points at the repository', async ({ page, context }) => {
    await openApp(page);
    const footer = page.locator('aside').getByRole('link');
    for (const [name, path] of [['Privacy', '/legal/privacy/'], ['Terms', '/legal/terms/'], ['Attributions', '/legal/attributions/']] as const) {
      const link = footer.filter({ hasText: new RegExp(`^${name}$`) });
      await expect(link).toHaveAttribute('href', path);
      const [popup] = await Promise.all([context.waitForEvent('page'), link.click()]);
      await popup.waitForLoadState();
      expect(new URL(popup.url()).pathname).toBe(path);
      await popup.close();
    }
    await expect(footer.filter({ hasText: /^Source code$/ })).toHaveAttribute('href', 'https://github.com/JJRPF/loam');
  });

  test('the sign-in screen links the Terms and Privacy Policy', async ({ page }) => {
    await openApp(page);
    await openTab(page, 'You');
    const agreement = page.getByText(/By continuing you agree to the/).locator('..');
    await expect(agreement.getByRole('link', { name: 'Terms' })).toHaveAttribute('href', '/legal/terms/');
    await expect(agreement.getByRole('link', { name: 'Privacy Policy' })).toHaveAttribute('href', '/legal/privacy/');
  });

  test('the map credit has a Legal link', async ({ page }) => {
    await openApp(page);
    await expect(page.locator('.map-attribution-badge').getByRole('link', { name: 'Legal' })).toHaveAttribute('href', '/legal/');
  });
});

for (const v of [ALL_VIEWPORTS[1], ALL_VIEWPORTS[4]]) {
  test(`build, shared link and directions at ${v.name}`, async ({ pageAt }) => {
    const page = await pageAt(v);
    await openApp(page);
    await page.getByRole('button', { name: 'Build Routes' }).first().click();
    await waitForResults(page);
    const shared = page.url();
    expect(shared).toMatch(/start=.*mode=loop.*terrain=/);
    await expect(page.locator('summary', { hasText: 'Directions' })).toHaveCount(1);
    await expect(page.getByText('Sign in to report a bad route')).toBeVisible();
    // the link re-runs the search in a fresh tab
    const other = await page.context().newPage();
    await other.goto(shared);
    await other.waitForSelector('article', { timeout: 90_000 });
    await other.close();
  });
}
