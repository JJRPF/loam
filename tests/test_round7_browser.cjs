// Round 7 browser checks (Playwright + system Chromium). Anonymous flows only: Firebase sign-in
// can't be driven without the Firebase web app, so signed-in UI (report modal, privacy controls)
// is checked in unit tests and by hand.
//   TEST_URL=http://127.0.0.1:8089 SHOTS=/some/dir node tests/test_round7_browser.cjs
const { chromium } = require('../frontend/node_modules/playwright');

const URL_ = process.env.TEST_URL || 'http://127.0.0.1:8089';
const SHOTS = process.env.SHOTS || '/tmp';
const results = [];
const check = (name, ok, detail = '') => {
  results.push({ name, ok });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ' - ' + detail : ''}`);
};

(async () => {
  const browser = await chromium.launch({
    executablePath: '/usr/local/bin/chromium',
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu']
  });
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, serviceWorkers: 'allow' });
  const page = await context.newPage();
  const consoleErrors = [];
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  const shot = (n) => page.screenshot({ path: `${SHOTS}/${n}.png` });

  try {
    await page.goto(URL_, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('canvas', { timeout: 15000 });
    check('map canvas renders', true);

    // Terrain mix: stacked bar with draggable dividers
    const bar = page.locator('[data-testid="terrain-bar"]');
    await bar.waitFor({ timeout: 5000 });
    const d0 = page.locator('[data-testid="terrain-divider-0"]');
    const before = await d0.getAttribute('aria-valuenow');
    await d0.focus();
    await page.keyboard.press('ArrowLeft');
    await page.keyboard.press('ArrowLeft');
    const afterKey = await d0.getAttribute('aria-valuenow');
    check('terrain divider moves with the keyboard', Number(afterKey) === Number(before) - 10, `${before} -> ${afterKey}`);
    const box = await d0.boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 - 60, box.y + box.height / 2, { steps: 5 });
    await page.mouse.up();
    const afterDrag = await d0.getAttribute('aria-valuenow');
    check('terrain divider moves by dragging', Number(afterDrag) < Number(afterKey), `${afterKey} -> ${afterDrag}`);
    await shot('plan-terrain');

    // Midpoints (point to point)
    await page.click('button:has-text("Point to Point")');
    await page.click('button:has-text("Add midpoint")');
    const mapBox = await page.locator('canvas').first().boundingBox();
    await page.mouse.click(mapBox.x + mapBox.width * 0.6, mapBox.y + mapBox.height * 0.5);
    const midRow = page.locator('text=/1\\. Midpoint/');
    check('a midpoint can be added by tapping the map', await midRow.count() === 1);
    await page.click('button[aria-label="Remove midpoint 1"]');
    check('a midpoint can be removed', await page.locator('text=/1\\. Midpoint/').count() === 0);
    await page.click('button:has-text("Loop / Round Trip")');

    // Build routes, shareable URL
    await page.click('button:has-text("Build Routes")');
    await page.waitForSelector('article', { timeout: 60000 });
    await page.waitForFunction(() => !document.body.innerText.includes('Calculating distinct candidate'), null, { timeout: 60000 }).catch(() => {});
    const cards = await page.locator('article').count();
    check('route cards stream in', cards >= 1, `${cards} cards`);
    const shared = page.url();
    check('the search is in the URL', /start=/.test(shared) && /mode=loop/.test(shared) && /terrain=/.test(shared), shared.replace(/^https?:\/\/[^/]+/, ''));
    await shot('results');

    check('results have a Directions list of steps', (await page.locator('summary:has-text("Directions")').count()) === 1);
    const waterBtn = page.locator('button:has-text("Water & shops")');
    // Bear Brook's own view has no mapped water or shops; look at Concord, where OSM has some
    await page.evaluate(() => window.__loamMap.jumpTo({ center: [-71.5376, 43.2081], zoom: 12.5 }));
    await page.waitForTimeout(1500);
    const poiResp = page.waitForResponse((r) => r.url().includes('/api/pois'), { timeout: 15000 });
    await waterBtn.click();
    check('water & shops toggle turns on', (await waterBtn.innerText()).includes('ON'));
    const pr = await poiResp;
    const poiJson = await pr.json();
    check('markers load for the view', pr.status() === 200 && poiJson.features.length > 0, `${poiJson.features.length} markers`);
    await page.waitForTimeout(1000);
    await shot('markers');
    await waterBtn.click();

    check('signed out: no Report bad route button, a sign-in hint instead',
      (await page.locator('button:has-text("Report bad route")').count()) === 0 &&
      (await page.locator('text=Sign in to report a bad route').count()) === 1);

    // Opening the shared link re-runs the search
    const page2 = await context.newPage();
    await page2.goto(shared, { waitUntil: 'domcontentloaded' });
    await page2.waitForSelector('article', { timeout: 60000 });
    check('opening a shared link re-runs the search', (await page2.locator('article').count()) >= 1);
    await page2.close();

    // Service worker and offline
    await page.goto(URL_, { waitUntil: 'load' });
    await page.evaluate(async () => { await navigator.serviceWorker.ready; });
    await page.reload({ waitUntil: 'load' });
    const controlled = await page.evaluate(() => !!navigator.serviceWorker.controller);
    check('service worker controls the page', controlled);
    await page.goto(shared, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('article', { timeout: 60000 }); // viewing stores the route
    await page.waitForTimeout(500);
    await context.setOffline(true);
    await page.goto(URL_, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('canvas', { timeout: 15000 });
    check('app shell loads offline', true);
    check('offline banner shows', await page.locator('text=Waiting for connection').count() === 1);
    await page.click('button:has-text("Saved")');
    await page.waitForSelector('text=Recently viewed', { timeout: 5000 });
    check('recently viewed routes are listed offline', true);
    await shot('offline-saved');
    await context.setOffline(false);

    // You panel: no preference controls that do nothing
    await page.goto(URL_, { waitUntil: 'domcontentloaded' });
    await page.click('button:has-text("You")');
    await page.waitForTimeout(500);
    const body = await page.innerText('body');
    const gone = ['Display Theme', 'Units', 'Endpoint Trimming', 'Privacy Threshold'].every((t) => !body.includes(t));
    check('You panel (signed out) has no theme, units, trimming or threshold controls', gone);
    // The preferences block (trimming sentence, DNR, privacy controls) renders only when signed in.
    check('no "Round N" copy in the UI', !/Round \d/.test(body));
    await shot('you');

    const bad = consoleErrors.filter((e) => !/firebase|identitytoolkit|ERR_INTERNET_DISCONNECTED|Failed to load resource.*(401|404)/i.test(e));
    check('no unexpected console errors', bad.length === 0, bad.slice(0, 3).join(' | '));
  } catch (err) {
    check('script ran to the end', false, String(err).split('\n')[0]);
    await shot('failure').catch(() => {});
  } finally {
    await browser.close();
    const failed = results.filter((r) => !r.ok).length;
    console.log(`\n${results.length - failed}/${results.length} checks passed`);
    process.exitCode = failed ? 1 : 0;
  }
})();
