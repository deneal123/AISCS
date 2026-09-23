const { test, expect, devices } = require('@playwright/test');

const noHorizontalOverflow = async (page) => {
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
};

test.describe('Responsive public UI', () => {
  test('landing has no horizontal overflow on desktop', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('heading', { name: /Одно окно/i })).toBeVisible();
    await noHorizontalOverflow(page);
  });

  test('mobile navigation and feature controls keep touch-sized targets', async ({ browser }) => {
    const context = await browser.newContext({ ...devices['iPhone 12'] });
    const page = await context.newPage();

    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const menu = page.getByRole('button', { name: 'Открыть меню' });
    await expect(menu).toBeVisible();
    const menuBox = await menu.boundingBox();
    expect(menuBox?.width).toBeGreaterThanOrEqual(44);
    expect(menuBox?.height).toBeGreaterThanOrEqual(44);

    await menu.click();
    await expect(page.getByRole('button', { name: 'Возможности' })).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByRole('button', { name: 'Возможности' })).toBeHidden();
    await page.getByRole('button', { name: /Показать: Диалоговые агенты/i }).scrollIntoViewIfNeeded();

    const orbitControl = page.getByRole('button', { name: /Показать: Диалоговые агенты/i });
    await expect(orbitControl).toBeVisible();
    const orbitBox = await orbitControl.boundingBox();
    expect(orbitBox?.width).toBeGreaterThanOrEqual(44);
    expect(orbitBox?.height).toBeGreaterThanOrEqual(44);
    await orbitControl.click();
    await noHorizontalOverflow(page);

    await context.close();
  });
});
