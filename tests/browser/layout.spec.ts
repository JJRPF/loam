import AxeBuilder from '@axe-core/playwright';
import type { Page } from '@playwright/test';
import {
  test, expect, openApp, openTab, signIn, overlaps,
  ALL_VIEWPORTS, MOBILE_VIEWPORTS, BEAR_BROOK_LINK, type Box,
} from './fixtures';

type PanelName = 'plan' | 'results' | 'explore' | 'saved' | 'you';

async function showPanel(page: Page, name: PanelName) {
  if (name === 'plan') { await openApp(page); await openTab(page, 'Plan'); return; }
  if (name === 'results') {
    await page.goto(BEAR_BROOK_LINK);
    await page.waitForSelector('article', { timeout: 90_000 });
    await page.waitForFunction(() => !document.body.innerText.includes('Calculating distinct candidate'), null, { timeout: 90_000 });
    return;
  }
  await openApp(page);
  await openTab(page, name === 'explore' ? 'Explore' : name === 'saved' ? 'Saved' : 'You');
}

const PANELS: PanelName[] = ['plan', 'results', 'explore', 'saved', 'you'];

/** Bounding boxes of everything that sits on the map surface (not inside the sheet's scroll content). */
async function mapFurniture(page: Page): Promise<Record<string, Box>> {
  return page.evaluate(() => {
    const out: Record<string, Box> = {};
    const add = (key: string, el: Element | null) => {
      if (!el) return;
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      if (r.width === 0 || r.height === 0 || cs.display === 'none' || cs.visibility === 'hidden') return;
      out[key] = { x: r.x, y: r.y, width: r.width, height: r.height };
    };
    type Box = { x: number; y: number; width: number; height: number };
    add('credit', document.querySelector('.map-attribution-badge'));
    document.querySelectorAll('main button').forEach((b) => {
      const label = (b.getAttribute('aria-label') || b.textContent || '').trim();
      if (/Heatmap/.test(label)) add('toggle:heatmap', b);
      else if (/About heat/.test(label)) add('toggle:heat-info-button', b);
      else if (/OTM Trails/.test(label)) add('toggle:otm', b);
      else if (/Zoom in/.test(label)) add('ctrl:zoom-in', b);
      else if (/Zoom out/.test(label)) add('ctrl:zoom-out', b);
      else if (/rotate map/.test(label)) add('ctrl:compass', b);
      else if (/Find my location/.test(label)) add('ctrl:locate', b);
    });
    add('heat-info', document.querySelector('main [role="note"]'));
    add('sheet-handle', document.querySelector('[data-testid="sheet-handle"]'));
    return out;
  });
}

function assertNoOverlaps(boxes: Record<string, Box>, ctx: string) {
  const keys = Object.keys(boxes);
  const clashes: string[] = [];
  for (let i = 0; i < keys.length; i++) {
    for (let j = i + 1; j < keys.length; j++) {
      if (overlaps(boxes[keys[i]], boxes[keys[j]])) clashes.push(`${keys[i]} x ${keys[j]}`);
    }
  }
  expect(clashes, `overlaps (${ctx}); present: ${keys.join(', ')}`).toEqual([]);
}

for (const v of MOBILE_VIEWPORTS) {
  test.describe(`map furniture does not overlap, ${v.name}`, () => {
    for (const snap of ['peek', 'half', 'full'] as const) {
      test(`sheet ${snap}, heat info open`, async ({ pageAt }) => {
        const page = await pageAt(v);
        await openApp(page);
        // heat info open (the heat layer is on by default); it is hidden again while the sheet is full
        await page.getByRole('button', { name: 'About heat' }).click({ timeout: 10_000 });
        const sheet = page.locator('[data-testid="sheet"]');
        const handle = page.locator('[data-testid="sheet-handle"]');
        const want: Record<string, string> = { peek: '110px', half: '52vh', full: '88vh' };
        for (let i = 0; i < 3; i++) {
          const h = await sheet.evaluate((el) => (el as HTMLElement).style.height);
          if (h === want[snap]) break;
          await handle.click({ position: { x: 5, y: 5 } });
          await page.waitForTimeout(400);
        }
        expect(await sheet.evaluate((el) => (el as HTMLElement).style.height)).toBe(want[snap]);
        assertNoOverlaps(await mapFurniture(page), `${v.name} ${snap}`);
        // the credit must be visible whenever the sheet leaves the map visible, and sit above the sheet
        if (snap !== 'full') {
          const credit = await page.locator('.map-attribution-badge').boundingBox();
          const sheetBox = await sheet.boundingBox();
          expect(credit, 'credit visible').not.toBeNull();
          expect(credit!.y + credit!.height).toBeLessThanOrEqual(sheetBox!.y);
        }
      });
    }
  });
}

for (const v of ALL_VIEWPORTS) {
  test.describe(`no horizontal scroll, ${v.name}`, () => {
    for (const panel of PANELS) {
      test(`${panel} panel`, async ({ pageAt }) => {
        const page = await pageAt(v);
        await showPanel(page, panel);
        const m = await page.evaluate(() => ({
          doc: document.documentElement.scrollWidth, body: document.body.scrollWidth, inner: window.innerWidth,
          // anything inside the panels wider than the viewport
          wide: [...document.querySelectorAll('aside *, section *, main *')]
            .filter((e) => {
              const r = e.getBoundingClientRect();
              if (r.width === 0 || r.right <= window.innerWidth + 1 || e.closest('canvas, .maplibregl-map')) return false;
              // content inside its own horizontal scroller (the hourly forecast strip) is not page overflow
              for (let p = e.parentElement; p && p !== document.body; p = p.parentElement) {
                const ox = getComputedStyle(p).overflowX;
                if ((ox === 'auto' || ox === 'scroll') && p.getBoundingClientRect().right <= window.innerWidth + 1) return false;
              }
              return true;
            })
            .slice(0, 5).map((e) => `${e.tagName}.${(e as HTMLElement).className}`.slice(0, 60)),
        }));
        expect(m.doc).toBeLessThanOrEqual(m.inner);
        expect(m.body).toBeLessThanOrEqual(m.inner);
        expect(m.wide).toEqual([]);
      });
    }
  });
}

for (const v of MOBILE_VIEWPORTS) {
  test.describe(`tap targets are at least 44 px, ${v.name}`, () => {
    for (const panel of PANELS) {
      test(`${panel} panel`, async ({ pageAt }) => {
        const page = await pageAt(v);
        await showPanel(page, panel);
        const small = await page.evaluate(() => {
          const bad: string[] = [];
          const check = (el: Element, rectEl: Element = el) => {
            const r = rectEl.getBoundingClientRect();
            const cs = getComputedStyle(rectEl);
            if (r.width === 0 || r.height === 0 || cs.visibility === 'hidden' || cs.display === 'none') return;
            if (r.width < 43.5 || r.height < 43.5) {
              bad.push(`${el.tagName} "${(el.getAttribute('aria-label') || el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 40)}" ${Math.round(r.width)}x${Math.round(r.height)}`);
            }
          };
          // buttons and summaries; checkboxes and radios through their label. The map credit links
          // (OpenStreetMap, CARTO, Legal) and the MapLibre scale bar are attribution text, not controls.
          document.querySelectorAll('button, summary, [role="button"]').forEach((e) => check(e));
          document.querySelectorAll('input[type="checkbox"], input[type="radio"]').forEach((e) => {
            const lab = (e as HTMLInputElement).labels?.[0] || e.closest('label');
            check(e, lab || e);
          });
          return bad;
        });
        expect(small).toEqual([]);
      });
    }
  });
}

test.describe('axe: no serious or critical violations', () => {
  // axe reads cross-origin stylesheets with fetch(), which the page's connect-src blocks; that is axe, not the app
  test.beforeEach(({ issues }) => { issues.allow(/fonts\.googleapis\.com/); });
  const v = { name: 'desktop-1280', width: 1280, height: 900 };
  const run = async (page: Page, what: string) => {
    const res = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
    const bad = res.violations.filter((x) => x.impact === 'serious' || x.impact === 'critical')
      .map((x) => `${x.id} (${x.impact}): ${x.nodes.slice(0, 4).map((n) => `${n.target.join(' ')} ${(n.any[0]?.message || n.failureSummary || '').replace(/\s+/g, ' ').slice(0, 160)}`).join(' | ')}`);
    expect(bad, `axe on ${what}`).toEqual([]);
  };
  for (const panel of PANELS) {
    test(`${panel} panel`, async ({ pageAt }) => {
      const page = await pageAt(v);
      await showPanel(page, panel);
      await page.waitForTimeout(500);
      await run(page, panel);
    });
  }
  test('sign-in card', async ({ pageAt }) => {
    const page = await pageAt(v);
    await openApp(page);
    await openTab(page, 'You');
    await page.waitForTimeout(500);
    await run(page, 'sign-in');
  });
  test('signed-in You panel', async ({ pageAt }) => {
    const page = await pageAt(v);
    await signIn(page);
    await page.waitForTimeout(800);
    await run(page, 'signed-in You');
  });
  for (const p of ['/legal/', '/legal/privacy/', '/legal/terms/', '/legal/attributions/']) {
    test(`legal page ${p}`, async ({ pageAt }) => {
      const page = await pageAt(v);
      await page.goto(p);
      await run(page, p);
    });
  }
});
