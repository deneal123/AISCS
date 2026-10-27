const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

test.use({ serviceWorkers: 'block' });
const index = fs.readFileSync(path.join(__dirname, '../../public/index.html'), 'utf8');
// Exercise the exact shipped discovery markup and real CSS/font assets, without
// app/API timing obscuring whether a late font can change an already painted run.
const links = index.match(/<link[^>]+(?:preload|stylesheet)[^>]+>/g)
  .filter((link) => link.includes('/static/fonts/'))
  .join('\n').replaceAll('%PUBLIC_URL%', '');

for (const useInter of [false, true]) {
  test(`не загружает неиспользуемые шрифты: ${useInter ? 'латиница Inter' : 'системный шрифт'}`, async ({ page }) => {
    const requests = [];
    page.on('request', (request) => {
      if (request.url().endsWith('.woff2')) requests.push(request.url().split('/').pop());
    });
    await page.route('**/__font_subset_probe', (route) => route.fulfill({
      contentType: 'text/html; charset=utf-8',
      body: `<!doctype html><html><head><meta charset="utf-8">${links}</head><body>
        <span style="font:450 24px ${useInter ? 'Inter,' : ''}system-ui,sans-serif">Interface</span>
        </body></html>`,
    }));
    await page.goto('/__font_subset_probe');
    await page.evaluate(() => document.fonts.ready);
    await expect(page.locator('span')).toHaveText('Interface');
    expect(requests).toEqual(useInter ? ['inter-latin-wght-normal.woff2'] : []);
    await expect(page.locator('link[rel="preload"][as="font"]')).toHaveCount(0);
  });
}

for (const unavailable of [false, true]) {
  test(`font ${unavailable ? 'failure' : 'late arrival'} retains readable first-paint geometry`, async ({ page, browserName }) => {
    let release;
    const held = new Promise((resolve) => { release = resolve; });
    await page.route('**/static/fonts/**/*.woff2', async (route) => {
      await held;
      if (unavailable) await route.abort();
      else await route.continue();
    });
    await page.route('**/__font_probe', (route) => route.fulfill({ contentType: 'text/html', body: `<!doctype html>
      <html lang="ru"><head><meta charset="utf-8">${links}</head><body>
      <span id="sample" style="font:450 24px Inter,system-ui,sans-serif">Проверка размера — English interface 123</span>
      <script>window.firstPaint = new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));</script>
      </body></html>` }));
    try {
      await page.goto('/__font_probe', { waitUntil: 'domcontentloaded' });
      const painted = await page.evaluate(() => Promise.race([
        window.firstPaint.then(() => true), new Promise((resolve) => setTimeout(() => resolve(false), 1500)),
      ]));
      // Keep the observed engine failure executable and visible, not a skip or
      // a green claim. A newly passing engine becomes an unexpected pass.
      test.fail(browserName === 'webkit',
        'P1-UI-FONT20261015: pending optional font blocks WebKit rendering frames; acceptance open');
      expect(painted, 'a pending optional font must not indefinitely block rendering frames').toBe(true);
      // Hold beyond the browser's brief optional-font block period. This is
      // intentional network fault injection, not an application readiness wait.
      await page.waitForTimeout(350);
      await expect(page.locator('#sample')).toBeVisible();
      const before = await page.locator('#sample').boundingBox();
      release();
      await page.evaluate(() => document.fonts.ready);
      // Observe another paint after resolution; checking only fonts.ready can
      // miss a layout change scheduled in the next rendering frame.
      await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      const after = await page.locator('#sample').boundingBox();
      expect(after.width).toBeCloseTo(before.width, 1);
      expect(after.height).toBeCloseTo(before.height, 1);
      expect(await page.locator('#sample').innerText()).toContain('Проверка размера');
    } finally { release(); }
  });
}
