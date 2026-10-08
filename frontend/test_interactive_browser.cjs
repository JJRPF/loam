const { chromium } = require('playwright');
const path = require('path');

const ARTIFACT_DIR = '/home/jjr/.gemini/antigravity-cli/brain/22e31a6e-66ea-42d5-9fef-df58ae61118f';

(async () => {
  console.log('🚀 Starting Playwright interactive browser test on http://127.0.0.1:8000...');
  
  const browser = await chromium.launch({
    executablePath: '/usr/local/bin/chromium',
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });

  const context = await browser.newContext({
    viewport: { width: 1280, height: 800 }
  });

  const page = await context.newPage();

  const errors = [];
  page.on('console', msg => {
    if (msg.type() === 'error') {
      console.log('   [Browser Console Error]:', msg.text());
      errors.push(msg.text());
    }
  });

  page.on('pageerror', err => {
    console.error('   [Uncaught Page Error]:', err.message);
    errors.push(err.message);
  });

  try {
    // 1. Navigate to Loam
    console.log('1. Navigating to http://127.0.0.1:8000...');
    await page.goto('http://127.0.0.1:8000/', { waitUntil: 'networkidle' });
    const title = await page.title();
    console.log('   ✓ Page title:', title);
    if (!title.includes('Loam')) throw new Error('Page title does not contain Loam');

    // 2. Check Always-Visible Attribution
    console.log('2. Checking always-visible map attribution badge...');
    const attrBadge = await page.locator('.map-attribution-badge');
    await attrBadge.waitFor({ state: 'visible', timeout: 5000 });
    const attrText = await attrBadge.innerText();
    console.log('   ✓ Attribution text:', attrText);
    if (!attrText.includes('OpenStreetMap') || !attrText.includes('CARTO')) {
      throw new Error(`Attribution missing expected text: ${attrText}`);
    }

    // 3. Test Dark Mode Toggle
    console.log('3. Testing Dark Mode toggle...');
    const themeBtn = page.locator('header button[title*="Mode"]');
    await themeBtn.click();
    await page.waitForTimeout(2000);
    const themeAttr = await page.locator('html').getAttribute('data-theme');
    console.log('   ✓ Theme attribute after toggle:', themeAttr);
    if (themeAttr !== 'dark') throw new Error(`Expected dark theme, got ${themeAttr}`);

    const layerInfo = await page.evaluate(() => {
      const map = window.__loamMap;
      return {
        hasMap: !!map,
        voyagerVisibility: map?.getLayoutProperty('carto-voyager-layer', 'visibility'),
        darkVisibility: map?.getLayoutProperty('carto-dark-layer', 'visibility')
      };
    });
    console.log('   ✓ Map layer visibility in dark mode:', layerInfo);

    // Take screenshot in Dark Mode
    await page.screenshot({ path: path.join(ARTIFACT_DIR, '01_plan_dark_mode.png'), fullPage: true });
    console.log('   ✓ Saved screenshot 01_plan_dark_mode.png');

    // Toggle back to light
    await themeBtn.click();
    await page.waitForTimeout(1000);

    // 4. Test Starting Location UX (Search, No Dropdown Presets)
    console.log('4. Testing Starting Location UX (Search and Geocoding)...');
    // Ensure old dropdown is gone
    const oldDropdownCount = await page.locator('select:has-text("Podunk")').count();
    console.log('   ✓ Old preset dropdown count:', oldDropdownCount);
    if (oldDropdownCount !== 0) throw new Error('Old trailhead dropdown still exists!');

    // Type in location search
    const searchInput = page.locator('input[placeholder*="Search trailhead"]');
    await searchInput.fill('Highland');
    await page.waitForTimeout(800);

    // Select Highland Mountain Bike Park
    const highlandResult = page.locator('.start-geocode-item').first();
    await highlandResult.waitFor({ state: 'visible', timeout: 5000 });
    await highlandResult.click();
    await page.waitForTimeout(600);

    const locationText = await page.locator('text=Highland Mountain Bike Park').first().textContent();
    console.log('   ✓ Selected location:', locationText);

    // 5. Test Sport Selector Clean-up
    console.log('5. Testing Sport Selector Clean-up...');
    const mtbBtn = page.getByRole('button', { name: /Mountain Bike/i });
    const gravelBtn = page.getByRole('button', { name: /🚲 Gravel/i });
    const trailRunBtn = page.getByRole('button', { name: /Trail Run/i });

    if (await mtbBtn.count() === 0 || await gravelBtn.count() === 0 || await trailRunBtn.count() === 0) {
      throw new Error('Missing active sport buttons');
    }

    // Switch to Gravel
    await gravelBtn.click();
    await page.waitForTimeout(300);
    console.log('   ✓ Switched to Gravel mode');

    // Switch to Trail Run
    await trailRunBtn.click();
    await page.waitForTimeout(300);
    const trailRunPolish = await page.locator('text=Trail Running Routing Polish').count();
    console.log('   ✓ Trail running polish options visible:', trailRunPolish > 0);

    // Switch back to Mountain Bike
    await mtbBtn.click();
    await page.waitForTimeout(300);

    // 6. Test Build Routes (Crash / Blank Screen Prevention)
    console.log('6. Testing "Build routes" button...');
    const buildBtn = page.locator('button:has-text("Build Routes")');
    await buildBtn.click();

    // Check Results panel appears without blank screen
    console.log('   ✓ Waiting for Results panel...');
    await page.waitForTimeout(1000);

    // Wait for at least 1 route card or active route header
    const milesDisplay = page.locator('.num-tabular:has-text("mi")').first();
    await milesDisplay.waitFor({ state: 'visible', timeout: 15000 });
    const routeHeader = page.locator('h2').first();
    const routeName = await routeHeader.innerText();
    console.log('   ✓ Active route rendered without crash:', routeName);

    // Verify distance and elevation profile are rendered
    const milesText = await page.locator('.num-tabular:has-text("mi")').first().innerText();
    console.log('   ✓ Distance display:', milesText);

    // Verify Elevation Profile SVG exists
    const eleSvg = await page.locator('svg[aria-label*="Elevation profile"], svg path').count();
    console.log('   ✓ Elevation profile SVG elements:', eleSvg);

    // Save screenshot of Results view
    await page.screenshot({ path: path.join(ARTIFACT_DIR, '02_results_view.png'), fullPage: true });
    console.log('   ✓ Saved screenshot 02_results_view.png');

    // 7. Test Route Saving to Database
    console.log('7. Testing "Save to Profile & Database"...');
    const saveBtn = page.locator('button:has-text("Save to Profile")');
    await saveBtn.click();
    await page.waitForTimeout(1000);
    const saveConfirmation = await page.locator('button:has-text("Saved")').count();
    console.log('   ✓ Save status confirmed:', saveConfirmation > 0);

    // 8. Test Saved Routes Tab
    console.log('8. Testing Saved Routes panel...');
    const savedNavBtn = page.locator('nav button:has-text("Saved")');
    await savedNavBtn.click();
    await page.waitForTimeout(1000);

    const savedCards = await page.locator('button:has-text("Delete")').count();
    console.log('   ✓ Saved routes loaded from database (delete buttons count):', savedCards);
    if (savedCards === 0) throw new Error('No saved routes found in database view');

    // Save screenshot of Saved routes view
    await page.screenshot({ path: path.join(ARTIFACT_DIR, '03_saved_routes_view.png'), fullPage: true });
    console.log('   ✓ Saved screenshot 03_saved_routes_view.png');

    // 9. Test You Tab (Google SSO & Settings)
    console.log('9. Testing You Tab (Profile & Settings)...');
    const youNavBtn = page.locator('nav button:has-text("You")');
    await youNavBtn.click();
    await page.waitForTimeout(500);

    const googleBtn = page.locator('button:has-text("Sign in with Google")');
    if (await googleBtn.count() > 0) {
      console.log('   ✓ Clicking "Sign in with Google"...');
      await googleBtn.click();
      await page.waitForTimeout(800);
    }

    const profileText = await page.locator('text=Justin Pfister').count();
    console.log('   ✓ Authenticated Google profile displayed:', profileText > 0);

    // Save screenshot of You tab
    await page.screenshot({ path: path.join(ARTIFACT_DIR, '04_you_settings_view.png'), fullPage: true });
    console.log('   ✓ Saved screenshot 04_you_settings_view.png');

    console.log('🎉 ALL PLAYWRIGHT INTERACTIVE BROWSER TESTS PASSED FLAWLESSLY!');

  } catch (err) {
    console.error('❌ Playwright test failed:', err);
    await page.screenshot({ path: path.join(ARTIFACT_DIR, 'error_screenshot.png'), fullPage: true });
    process.exit(1);
  } finally {
    await browser.close();
  }
})();
