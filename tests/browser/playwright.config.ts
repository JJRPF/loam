import { defineConfig } from '@playwright/test';
import fs from 'node:fs';

// Run from frontend/:  npm run test:browser   (builds the test bundle first; see scripts/run-browser-tests.sh)
// Target: a production build served by a Hosting stand-in (:5180), the real API on loopback (:8089) with the dev
// database, and the Firebase Auth emulator (:9099, project demo-loam). Nothing here talks to production.
const chromium = ['/usr/local/bin/chromium', '/usr/bin/chromium', '/usr/bin/chromium-browser'].find((p) => fs.existsSync(p));

export const WEB = 'http://127.0.0.1:5180';
export const API = 'http://127.0.0.1:8089';
export const LIMITED_API = 'http://127.0.0.1:8091';
export const MIDPOINT_API = 'http://127.0.0.1:8092';
export const EMULATOR = 'http://127.0.0.1:9099';

export default defineConfig({
  testDir: '.',
  testMatch: /.*\.spec\.ts/,
  testIgnore: /smoke\.prod\.spec\.ts/,
  workers: 1,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  retries: 0,
  reporter: [['list']],
  outputDir: process.env.PW_OUTPUT_DIR || '/tmp/loam-browser-results',
  use: {
    baseURL: WEB,
    colorScheme: 'dark',
    launchOptions: {
      executablePath: chromium,
      args: [
        '--no-sandbox', '--disable-gpu', '--ignore-gpu-blocklist', '--use-gl=angle', '--use-angle=swiftshader',
      ],
    },
  },
  webServer: [
    { command: '../../scripts/browser-test-emulator.sh', url: EMULATOR, reuseExistingServer: true, timeout: 120_000 },
    { command: '../../scripts/browser-test-server.sh 8089', url: `${API}/health`, reuseExistingServer: true, timeout: 120_000 },
    // a second API with a tiny geocode budget, to see a real 429 (the main one allows 1000 a minute)
    { command: '../../scripts/browser-test-server.sh 8091 RATE_LIMIT_GEOCODE=3/60', url: `${LIMITED_API}/health`, reuseExistingServer: true, timeout: 120_000 },
    // a third API with midpoints on, for midpoints.spec.ts (the bundle's API is :8089, flag off; that spec redirects to this one)
    { command: '../../scripts/browser-test-server.sh 8092 ENABLE_MIDPOINTS=true', url: `${MIDPOINT_API}/health`, reuseExistingServer: true, timeout: 120_000 },
    {
      command: 'node hosting-server.mjs 5180',
      url: `${WEB}/`,
      reuseExistingServer: true,
      env: { CSP_CONNECT_EXTRA: `${API} ${EMULATOR}` },
    },
  ],
});
