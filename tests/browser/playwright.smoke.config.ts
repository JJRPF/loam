import { defineConfig } from '@playwright/test';
import fs from 'node:fs';

// Read-only smoke test of the live site. Run by hand, after a deploy:
//   BASE_URL=https://loam.thepfisters.com npx playwright test -c ../tests/browser/playwright.smoke.config.ts
// (from frontend/). It never signs in, saves, uploads or reports.
const chromium = ['/usr/local/bin/chromium', '/usr/bin/chromium', '/usr/bin/chromium-browser'].find((p) => fs.existsSync(p));

export default defineConfig({
  testDir: '.',
  testMatch: /smoke\.prod\.spec\.ts/,
  workers: 1,
  timeout: 120_000,
  expect: { timeout: 20_000 },
  reporter: [['list']],
  outputDir: process.env.PW_OUTPUT_DIR || '/tmp/loam-browser-smoke',
  use: {
    baseURL: process.env.BASE_URL || 'https://loam.thepfisters.com',
    launchOptions: { executablePath: chromium, args: ['--no-sandbox', '--disable-gpu', '--use-gl=angle', '--use-angle=swiftshader'] },
  },
});
