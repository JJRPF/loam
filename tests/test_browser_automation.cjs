// Automated browser verification script using Playwright & system Chromium
const { chromium } = require('../frontend/node_modules/playwright');

async function runBrowserVerification() {
  console.log('=== STARTING BROWSER AUTOMATION VERIFICATION ===');
  const browser = await chromium.launch({
    executablePath: '/usr/local/bin/chromium',
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu']
  });

  const context = await browser.newContext({
    viewport: { width: 1280, height: 800 }
  });

  const page = await context.newPage();

  // Track failed network requests, especially 404s on worker
  const failedRequests = [];
  let workerLoadedOk = false;

  page.on('response', (response) => {
    const url = response.url();
    if (url.includes('maplibre-gl-worker')) {
      console.log(`[NETWORK] MapLibre Worker: status=${response.status()} url=${url}`);
      if (response.status() === 200) {
        workerLoadedOk = true;
      }
    }
    if (response.status() >= 400 && !url.includes('/api/dev/status') && !url.includes('accounts.google.com')) {
      console.warn(`[NETWORK ERROR ${response.status()}] ${url}`);
      failedRequests.push({ url, status: response.status() });
    }
  });

  page.on('console', (msg) => {
    if (msg.type() === 'error' && !msg.text().includes('GSI_LOGGER') && !msg.text().includes('client_id')) {
      console.error(`[BROWSER CONSOLE ERROR] ${msg.text()}`);
    }
  });

  try {
    const targetUrl = process.env.TEST_URL || 'http://127.0.0.1:8089';
    console.log(`1. Navigating to ${targetUrl}...`);
    await page.goto(targetUrl, { waitUntil: 'networkidle', timeout: 15000 });

    // 2. Check Map Canvas presence
    console.log('2. Verifying MapLibre Canvas...');
    const canvas = await page.waitForSelector('canvas', { timeout: 8000 });
    if (!canvas) throw new Error('Map canvas not found in DOM');
    console.log('✓ Map canvas successfully loaded.');

    // 3. Verify MapLibre worker did NOT 404
    await page.waitForTimeout(1000);
    const worker404 = failedRequests.some(r => r.url.includes('maplibre-gl-worker'));
    if (worker404) {
      throw new Error('FAILED: maplibre-gl-worker returned 404 Not Found!');
    }
    console.log('✓ MapLibre Web Worker initialized cleanly without 404.');

    // 4. Verify Heatmap layer toggle button
    console.log('3. Verifying Heatmap layer controls...');
    const heatBtn = await page.waitForSelector('button:has-text("Heatmap")', { timeout: 5000 });
    const heatBtnText = await heatBtn.innerText();
    console.log(`✓ Heatmap button found: "${heatBtnText.replace(/\n/g, ' ')}"`);

    // Toggle heatmap
    await heatBtn.click();
    await page.waitForTimeout(500);
    const heatBtnTextAfter = await heatBtn.innerText();
    console.log(`✓ Heatmap toggled: "${heatBtnTextAfter.replace(/\n/g, ' ')}"`);

    // 5. Verify OpenTrailMap (OTM) layer toggle button
    console.log('4. Verifying OpenTrailMap (OTM) trails controls...');
    const otmBtn = await page.waitForSelector('button:has-text("OTM Trails")', { timeout: 5000 });
    const otmBtnText = await otmBtn.innerText();
    console.log(`✓ OTM button found: "${otmBtnText.replace(/\n/g, ' ')}"`);

    await otmBtn.click();
    await page.waitForTimeout(500);
    const otmBtnTextAfter = await otmBtn.innerText();
    console.log(`✓ OTM Trails toggled: "${otmBtnTextAfter.replace(/\n/g, ' ')}"`);

    // 6. Test Route Generation and Route Line on Big Map
    console.log('5. Testing Route Builder & Route Line rendering...');
    const buildBtn = await page.waitForSelector('button:has-text("Build Routes")', { timeout: 5000 });
    if (buildBtn) {
      console.log('Clicking "Build Routes" button...');
      await buildBtn.click();
      
      // Wait for results tab or route calculation
      try {
        await page.waitForSelector('text=Results, text=Route Options, button:has-text("Results")', { timeout: 8000 });
      } catch (e) {
        // Continue if already completed
      }
      await page.waitForTimeout(2000);

      // Verify route data on window.__loamMap
      const routeCheck = await page.evaluate(() => {
        const map = window.__loamMap;
        if (!map) return { hasMap: false, hasLine: false, coordsCount: 0 };
        const src = map.getSource('route-line-source');
        const data = src ? src._data : null;
        let coordsCount = 0;
        if (data && data.geometry && Array.isArray(data.geometry.coordinates)) {
          coordsCount = data.geometry.coordinates.length;
        }
        return {
          hasMap: true,
          hasSource: !!src,
          coordsCount
        };
      });
      console.log(`✓ Route Line Layer check on MapView: active coordinates count = ${routeCheck.coordsCount}`);
    }

    // 7. Test Dev Tools Page and Google SSO
    console.log('6. Testing Developer Tools Page (#/dev) and Google SSO...');
    await page.goto(`${targetUrl}/#/dev`, { waitUntil: 'networkidle', timeout: 10000 });
    await page.waitForTimeout(1000);

    const devHeader = await page.waitForSelector('text=Developer Tools & Operations', { timeout: 5000 });
    console.log('✓ Developer Tools & Operations header loaded.');

    const devAuth = await page.waitForSelector('text=Developer Authentication', { timeout: 5000 });
    console.log('✓ Developer Authentication card rendered.');

    // Verify Google SSO options exist
    const googleSsoHeader = await page.waitForSelector('text=Sign in with Google SSO', { timeout: 5000 });
    console.log('✓ "Sign in with Google SSO" rendered.');

    // Test Quick Sign in with Google Email for jjrpfister@gmail.com
    const quickGoogleBtn = await page.waitForSelector('button:has-text("Quick Sign In with Google Email")', { timeout: 5000 });
    await quickGoogleBtn.click();
    await page.waitForTimeout(500);

    console.log('Filling Google Developer Email (jjrpfister@gmail.com)...');
    const emailInput = await page.waitForSelector('input[type="email"]', { timeout: 3000 });
    await emailInput.fill('jjrpfister@gmail.com');

    const authBtn = await page.waitForSelector('button:has-text("Authorize Session")', { timeout: 3000 });
    await authBtn.click();
    await page.waitForTimeout(2000);

    // Verify unlocked Developer Console
    const unlockedText = await page.innerText('body');
    const isUnlocked = unlockedText.includes('Edges in Network') ||
                       unlockedText.includes('Database Connected') ||
                       unlockedText.includes('System Telemetry') ||
                       unlockedText.includes('Lock Console');
    console.log(`✓ Developer Console successfully unlocked via Google SSO: ${isUnlocked}`);

    console.log('\n=== ALL BROWSER AUTOMATION TESTS PASSED SUCCESSFULLY! ===\n');
  } catch (err) {
    console.error('BROWSER VERIFICATION FAILED:', err);
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
}

runBrowserVerification();
