const { test, expect } = require('@playwright/test');

const publicSurfaces = ['/', '/login', '/pricing', '/chat'];

test.describe('responsive public surfaces', () => {
  for (const path of publicSurfaces) {
    test(`${path} has no page-level horizontal overflow`, async ({ page }) => {
      await page.goto(path, { waitUntil: 'domcontentloaded' });
      await expect(page.locator('body')).toBeVisible();

      const dimensions = await page.evaluate(() => ({
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
      }));
      expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
    });
  }

  test('keyboard focus stays visible on the mobile navigation control', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'Touch target assertion applies to mobile projects.');
    await page.goto('/', { waitUntil: 'domcontentloaded' });

    const menu = page.getByRole('button', { name: /меню/i });
    await expect(menu).toBeVisible();
    const box = await menu.boundingBox();
    expect(box.width).toBeGreaterThanOrEqual(44);
    expect(box.height).toBeGreaterThanOrEqual(44);

    await page.keyboard.press('Tab');
    await expect(page.locator(':focus')).toBeVisible();
  });

  test('320 px keeps every public surface within the viewport', async ({ page, isMobile }) => {
    test.skip(!isMobile, 'Narrowest-width assertion applies to mobile projects.');
    await page.setViewportSize({ width: 320, height: 844 });

    for (const path of publicSurfaces) {
      await page.goto(path, { waitUntil: 'domcontentloaded' });
      const dimensions = await page.evaluate(() => ({
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
      }));
      expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
    }
  });
});
