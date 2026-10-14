import { test, expect, openApp, signIn, openTab, TEST_EMAIL } from './fixtures';

test('the app loads, the map renders, nothing logs an error', async ({ page }) => {
  await openApp(page);
  await expect(page.locator('canvas').first()).toBeVisible();
  await page.waitForTimeout(1500);
});

test('the issue watcher itself catches a CSP violation and a failed request', async ({ page, issues }) => {
  await openApp(page);
  await page.evaluate(() => { fetch('https://example.invalid/x').catch(() => {}); });
  await page.waitForTimeout(500);
  const csp = await page.evaluate(() => (window as any).__csp as string[]);
  expect(csp.join()).toContain('connect-src');
  issues.allow(/example\.invalid|connect-src|Content Security Policy|Refused to connect/i);
});

test('sign-in through the emulator email link works end to end', async ({ page }) => {
  await signIn(page);
  await openTab(page, 'You');
  await expect(page.getByText(TEST_EMAIL).first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible();
});
