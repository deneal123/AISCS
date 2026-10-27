const { test, expect } = require('@playwright/test');
const { installLibraryApi } = require('./helpers/libraryApi');

test.use({ serviceWorkers: 'block' });

for (const width of [393, 851]) test(`bottom safe inset remains owned above and below the mobile breakpoint ${width}px`, async ({ page }) => {
  // Wide phone/tablet breakpoint, not native orientation or Home bar emulation.
  await page.setViewportSize({ width, height: 851 });
  await installLibraryApi(page);
  await page.evaluate(() => document.documentElement.style.setProperty('--app-safe-bottom', '21px'));
  const composer = page.locator('[data-composer-container]');
  await expect.poll(() => composer.evaluate(element => parseFloat(getComputedStyle(element).paddingBottom))).toBe(width < 768 ? 33 : 29);
  const input = page.getByRole('textbox', { name: 'Сообщение', exact: true });
  await expect(input).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
