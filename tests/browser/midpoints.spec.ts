// GH-41: midpoints with ENABLE_MIDPOINTS=true. The bundle talks to the flag-off API on :8089; here every /api
// request of the page is redirected to a second API on :8092 started with ENABLE_MIDPOINTS=true (see
// playwright.config.ts), so the flag-off suite (features.spec.ts) is untouched. Public trailheads only: the
// scenarios are benchmark/via_scenarios.json (trailheads from OSM, midpoints picked from OSM trail segments).
import fs from 'node:fs';
import path from 'node:path';
import { test, expect, openApp, type Page } from './fixtures';
import { API, MIDPOINT_API } from './playwright.config';

const MID_API = MIDPOINT_API;
const SCENARIOS: any[] = JSON.parse(fs.readFileSync(path.resolve(process.cwd(), '../benchmark/via_scenarios.json'), 'utf8')).scenarios;
const scenario = (id: string) => SCENARIOS.find((s) => s.id === id);
const VIA_TOLERANCE_M = 150; // the engine's hard bound for how far a route may pass from a midpoint

async function useMidpointApi(page: Page) {
  await page.route(`${API}/**`, (route) => route.continue({ url: route.request().url().replace(API, MID_API) }));
}

function link(sc: any, vias: number[][] = sc.waypoints, miles = sc.miles) {
  const q = new URLSearchParams({ sport: 'mtb_hardtail', start: `${sc.start[0].toFixed(5)},${sc.start[1].toFixed(5)}`, sn: sc.name,
    mode: 'loop', mi: String(miles), terrain: '60,20,10,10' });
  vias.forEach((v) => q.append('via', `${v[0].toFixed(5)},${v[1].toFixed(5)}`));
  return `/?${q.toString()}`;
}

const rad = (d: number) => (d * Math.PI) / 180;
function haversineM(a: number[], b: number[]) { // [lon, lat]
  const dp = rad(b[1] - a[1]), dl = rad(b[0] - a[0]);
  const h = Math.sin(dp / 2) ** 2 + Math.cos(rad(a[1])) * Math.cos(rad(b[1])) * Math.sin(dl / 2) ** 2;
  return 2 * 6371008.8 * Math.asin(Math.sqrt(h));
}
const closestM = (coords: number[][], lat: number, lon: number) => Math.min(...coords.map((c) => haversineM(c, [lon, lat])));

interface Stream { candidates: any[]; notice: string | null }
async function readStream(resp: { text(): Promise<string> }): Promise<Stream> {
  const text = await resp.text();
  const candidates: any[] = [];
  let notice: string | null = null;
  for (const block of text.split('\n\n')) {
    const ev = /^event: (\w+)/m.exec(block)?.[1];
    const data = /^data: (.*)$/m.exec(block)?.[1];
    if (!ev || !data) continue;
    if (ev === 'candidate') candidates.push(JSON.parse(data));
    if (ev === 'complete') notice = JSON.parse(data).notice ?? null;
  }
  return { candidates, notice };
}

/** Builds the routes and returns what the page received from the API. */
async function build(page: Page): Promise<Stream> {
  const got = page.waitForResponse((r) => r.url().includes('/api/route/options/stream') && r.request().method() === 'POST', { timeout: 90_000 });
  await page.getByRole('button', { name: 'Build Routes' }).first().click();
  const stream = await readStream(await got);
  await page.waitForFunction(() => !document.body.innerText.includes('Calculating distinct candidate'), null, { timeout: 90_000 });
  return stream;
}

function expectPassesMidpoints(stream: Stream, vias: { lat: number; lon: number }[]) {
  expect(stream.candidates.length, 'the API returned routes').toBeGreaterThan(0);
  for (const c of stream.candidates) {
    for (const [i, v] of vias.entries()) {
      expect(closestM(c.coordinates, v.lat, v.lon), `${c.name}: closest approach to midpoint ${i + 1} (m)`).toBeLessThanOrEqual(VIA_TOLERANCE_M);
    }
  }
}

/** Reads "Midpoint (43.1234, -71.5678)" rows of the Plan panel. */
async function midpointRows(page: Page) {
  const rows = await page.getByTestId('midpoint-row').allInnerTexts();
  return rows.map((t) => {
    const m = /\((-?\d+\.\d+), (-?\d+\.\d+)\)/.exec(t);
    return m ? { lat: Number(m[1]), lon: Number(m[2]) } : null;
  });
}

/** A link opens on Results (its search runs on load); this returns to the Plan form. */
async function backToPlan(page: Page) {
  await page.getByRole('button', { name: /edit plan/i }).first().click();
  await expect(page.getByRole('button', { name: /add midpoint/i })).toBeVisible();
}

const merc = (lat: number) => Math.log(Math.tan(Math.PI / 4 + rad(lat) / 2));

/** Taps the map twice to learn how pixels map to coordinates, then taps the wanted point. */
async function tapMapAt(page: Page, lat: number, lon: number) {
  const box = (await page.locator('canvas').first().boundingBox())!;
  const probe = async (x: number, y: number) => {
    await page.getByRole('button', { name: /add midpoint/i }).click();
    await page.mouse.click(x, y);
    const rows = await midpointRows(page);
    const p = rows[rows.length - 1]!;
    await page.getByRole('button', { name: `Remove midpoint ${rows.length}` }).click();
    return p;
  };
  const x1 = box.x + box.width * 0.55, y1 = box.y + box.height * 0.40;
  const x2 = box.x + box.width * 0.85, y2 = box.y + box.height * 0.70;
  const a = await probe(x1, y1), b = await probe(x2, y2);
  const x = x1 + ((lon - a.lon) * (x2 - x1)) / (b.lon - a.lon);
  const y = y1 + ((merc(lat) - merc(a.lat)) * (y2 - y1)) / (merc(b.lat) - merc(a.lat));
  expect(x > box.x && x < box.x + box.width && y > box.y && y < box.y + box.height, `the point is on the map (${x | 0}, ${y | 0})`).toBe(true);
  await page.getByRole('button', { name: /add midpoint/i }).click();
  await page.mouse.click(x, y);
}

test.describe('midpoints are on (ENABLE_MIDPOINTS=true)', () => {
  const sc = scenario('v1_bear_brook_5mi_b135');

  test('a midpoint added by tapping the map is on the route; removing it and rebuilding works', async ({ page }) => {
    test.skip(!sc, 'scenario missing');
    await useMidpointApi(page);
    await page.setViewportSize({ width: 1280, height: 900 });
    await openApp(page, link(sc, []));
    await backToPlan(page);
    const [lat, lon] = sc.waypoints[0];
    await tapMapAt(page, lat, lon);
    const rows = await midpointRows(page);
    expect(rows).toHaveLength(1);
    expect(rows[0], 'the tapped midpoint carries its coordinates').not.toBeNull();
    const stream = await build(page);
    expectPassesMidpoints(stream, [rows[0]!]);

    await backToPlan(page);
    await page.getByRole('button', { name: 'Remove midpoint 1' }).click();
    expect(await midpointRows(page)).toHaveLength(0);
    const plain = await build(page);
    expect(plain.candidates.length).toBeGreaterThan(0);
  });

  test('reordering two midpoints rebuilds a route that passes them in the new order', async ({ page }) => {
    const two = scenario('v2_oak_hill_10mi_b30');
    test.skip(!two, 'scenario missing');
    await useMidpointApi(page);
    await page.setViewportSize({ width: 1280, height: 900 });
    await openApp(page, link(two));
    await backToPlan(page);
    await expect(page.getByTestId('midpoint-row')).toHaveCount(2);
    await page.getByRole('button', { name: 'Move midpoint 2 up' }).click();
    const [v1, v2] = two.waypoints;
    const stream = await build(page);
    // the search link records the midpoints in their new order: the scenario's second one first
    const vias = new URL(page.url()).searchParams.getAll('via');
    expect(vias).toEqual([`${v2[0].toFixed(5)},${v2[1].toFixed(5)}`, `${v1[0].toFixed(5)},${v1[1].toFixed(5)}`]);
    expect(stream.candidates.length, `routes for the reordered midpoints (API notice: ${stream.notice})`).toBeGreaterThan(0);
    for (const c of stream.candidates) {
      const first = c.coordinates.findIndex((p: number[]) => haversineM(p, [v2[1], v2[0]]) <= VIA_TOLERANCE_M);
      const later = c.coordinates.findIndex((p: number[], i: number) => i > first && haversineM(p, [v1[1], v1[0]]) <= VIA_TOLERANCE_M);
      expect(first, `${c.name}: reaches the first midpoint`).toBeGreaterThanOrEqual(0);
      expect(later, `${c.name}: then the second`).toBeGreaterThan(first);
    }
  });

  test('a shared link with via= reproduces the same routes', async ({ page }) => {
    test.skip(!sc, 'scenario missing');
    await useMidpointApi(page);
    const first = page.waitForResponse((r) => r.url().includes('/api/route/options/stream'), { timeout: 90_000 });
    await openApp(page, link(sc));
    const a = await readStream(await first);
    expect(page.url()).toContain('via=');
    expectPassesMidpoints(a, [{ lat: sc.waypoints[0][0], lon: sc.waypoints[0][1] }]);
    const second = page.waitForResponse((r) => r.url().includes('/api/route/options/stream'), { timeout: 90_000 });
    await page.goto(page.url());
    const b = await readStream(await second);
    const sig = (s: Stream) => s.candidates.map((c) => `${c.name}|${c.distance_miles}|${c.coordinates.length}`).sort();
    expect(sig(b)).toEqual(sig(a));
  });

  test('the dead-end notice is shown when the API sends one', async ({ page }) => {
    // the engine's notice text is exercised against the real network in tests/test_round9_midpoints_live.py;
    // here the page must show what the API says, so the stream is answered with a notice
    await useMidpointApi(page);   // a later page.route takes precedence over an earlier one, so the stream override below wins
    await page.route(`${API}/api/route/options/stream`, async (route) => {
      const body = await (await route.fetch({ url: `${MID_API}/api/route/options/stream` })).text();
      const notice = 'A midpoint can only be reached by a spur that you ride out and back, so part of this route repeats the same trail. Move the midpoint to a through trail for a true loop.';
      await route.fulfill({ status: 200, contentType: 'text/event-stream',
        headers: { 'access-control-allow-origin': 'http://127.0.0.1:5180' },
        body: body.replace(/(event: complete\ndata: )(\{.*\})/, (_m, h, j) => h + JSON.stringify({ ...JSON.parse(j), notice })) });
    });
    await openApp(page, link(sc));
    await expect(page.getByText(/ride out and back/i).first()).toBeVisible({ timeout: 90_000 });
  });

  test('at 360 px the midpoint controls are 44 px tall and do not overlap', async ({ pageAt }) => {
    const three = scenario('v3_knox_10mi');
    test.skip(!three, 'scenario missing');
    const page = await pageAt({ width: 360, height: 740 });
    await useMidpointApi(page);
    await openApp(page, link(three));
    await page.getByRole('button', { name: 'Plan', exact: true }).first().click().catch(() => {});
    const rows = page.getByTestId('midpoint-row');
    await expect(rows).toHaveCount(3);
    const boxes: { x: number; y: number; width: number; height: number }[] = [];
    for (const label of [/add midpoint/i, /move midpoint 1 down/i, /move midpoint 2 up/i, /remove midpoint 1/i, /remove midpoint 3/i]) {
      const b = page.getByRole('button', { name: label }).first();
      await b.scrollIntoViewIfNeeded();
      const box = (await b.boundingBox())!;
      expect(box.height, `${label} height`).toBeGreaterThanOrEqual(44);
      if (!/add midpoint/i.test(String(label))) expect(box.width, `${label} width`).toBeGreaterThanOrEqual(44);
      boxes.push(box);
    }
    const first = rows.first();
    const btns = await first.getByRole('button').all();
    const bb = await Promise.all(btns.map((b) => b.boundingBox()));
    for (let i = 0; i < bb.length; i++) for (let j = i + 1; j < bb.length; j++) {
      const A = bb[i]!, B = bb[j]!;
      expect(A.x + A.width <= B.x + 0.5 || B.x + B.width <= A.x + 0.5 || A.y + A.height <= B.y || B.y + B.height <= A.y, `buttons ${i} and ${j} overlap`).toBe(true);
    }
    for (const b of bb) expect(b!.x + b!.width, 'inside the viewport').toBeLessThanOrEqual(360);
  });
});
