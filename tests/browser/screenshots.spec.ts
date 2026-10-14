// README screenshots (docs/screenshots/): real app output at Bear Brook State Park, signed in with an emulator
// account. Run on purpose, never as part of the normal suite:   SHOTS=1 npm run test:browser -- screenshots
import path from 'node:path';
import type { Page } from '@playwright/test';
import { test, expect, openApp, openTab, signIn, BEAR_BROOK_LINK } from './fixtures';

const OUT = path.resolve(__dirname, '../../docs/screenshots');
test.skip(!process.env.SHOTS, 'screenshots are taken only with SHOTS=1');
test.describe.configure({ mode: 'serial' });

async function results(page: Page) {
  await page.goto(BEAR_BROOK_LINK);
  await page.waitForSelector('article', { timeout: 90_000 });
  await page.waitForFunction(() => !document.body.innerText.includes('Calculating distinct candidate'), null, { timeout: 90_000 });
  await page.waitForTimeout(2500); // tiles and the route line settle
}

test('hero-desktop: results over the heat layer, strip and elevation visible', async ({ pageAt }) => {
  const page = await pageAt({ width: 1440, height: 900 });
  await signIn(page);
  await results(page);
  await page.screenshot({ path: `${OUT}/hero-desktop.png` });
});

// Bear Brook has almost no public heat in the dev database, so the heat shot is taken at another public trail
// network from the app's own trailhead list (Bow Town Forest), where the layer is visible. It is not a place the
// owner starts rides from often (checked locally against the Garmin export; nothing from that check is committed).
test('heatmap: the heat layer with its info text', async ({ pageAt }) => {
  const page = await pageAt({ width: 1440, height: 900 });
  await openApp(page);
  await page.getByPlaceholder(/search trailhead or town/i).fill('Bow Town Forest');
  await page.getByTestId('start-geocode-item').first().click(); // the start moves to the app's own trailhead entry and the map follows
  await page.waitForTimeout(3000);
  await page.getByRole('button', { name: 'About heat' }).click();
  await expect(page.getByRole('note')).toBeVisible();
  await page.waitForTimeout(4000);
  await page.screenshot({ path: `${OUT}/heatmap.png` });
});

test('mobile-plan: the Plan panel', async ({ pageAt }) => {
  const page = await pageAt({ width: 390, height: 844 });
  await openApp(page);
  await openTab(page, 'Plan');
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${OUT}/mobile-plan.png` });
});

test('mobile-results: results sheet half open with the route on the map', async ({ pageAt }) => {
  const page = await pageAt({ width: 390, height: 844 });
  await results(page);
  await page.screenshot({ path: `${OUT}/mobile-results.png` });
});

test('route-detail and export: close-ups of one candidate', async ({ pageAt }) => {
  const page = await pageAt({ width: 1440, height: 900 });
  await results(page);
  const profile = page.getByTestId('elevation-profile').first();
  await profile.scrollIntoViewIfNeeded();
  const clip = async (loc: ReturnType<Page['locator']>, pad: number, file: string) => {
    const b = (await loc.boundingBox())!;
    await page.screenshot({ path: `${OUT}/${file}`, clip: { x: Math.max(0, b.x - pad), y: Math.max(0, b.y - pad), width: b.width + 2 * pad, height: b.height + 2 * pad } });
  };
  // the panel section that holds the profile and the strip
  await clip(profile.locator('xpath=ancestor::*[.//*[@data-testid="surface-strip"]][1]'), 10, 'route-detail.png');
  const gpx = page.getByRole('button', { name: 'Download GPX' });
  await gpx.scrollIntoViewIfNeeded();
  await clip(page.getByRole('button', { name: 'Share to Garmin Connect' }).locator('xpath=..'), 10, 'export.png');
});

test('you-privacy: the You panel with privacy controls (emulator account)', async ({ pageAt }) => {
  const page = await pageAt({ width: 1440, height: 900 });
  await signIn(page);
  await expect(page.getByText(/privacy zones?/i).first()).toBeVisible();
  await page.getByText(/privacy zones?/i).first().scrollIntoViewIfNeeded();
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${OUT}/you-privacy.png` });
});
