const { test, expect } = require('@playwright/test');

// Policy/scale admission coverage only; native pinch acceptance remains open.
test.skip(({ browserName }) => browserName !== 'chromium', 'Touch synthesis requires Chromium CDP');
test.use({ channel: 'chromium', viewport: { width: 393, height: 851 }, isMobile: true, hasTouch: true, serviceWorkers: 'block' });

async function fixture(page) {
  await page.route('https://fonts.googleapis.com/**', (route) => route.fulfill({ contentType: 'text/css', body: '' }));
  await page.route('https://fonts.gstatic.com/**', (route) => route.abort());
  await page.addInitScript(() => {
    localStorage.setItem('telerag:isAuthenticated', 'true');
    localStorage.setItem('auth_token', 'gesture-fixture-token');
  });
  await page.routeWebSocket('**/api/**', () => {});
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    let json = {};
    if (path === '/api/profile/me') json = { id: 'gesture-user', email: 'gesture@example.test', permissions: [] };
    if (path === '/api/chats/') json = { chats: [{ thread_id: 'gesture-fixture', title: 'Проверка жестов' }] };
    if (path === '/api/chats/gesture-fixture') json = { messages: [] };
    if (path.endsWith('/trace')) json = { traces: {} };
    if (path.endsWith('/personas')) json = { personas: [] };
    if (path.endsWith('/models/catalog')) json = { models: [], providers: [] };
    if (path.endsWith('/transcription/config')) json = { enabled: false };
    await route.fulfill({ json });
  });
  await page.goto('/chat/gesture-fixture');
  await expect(page.getByRole('textbox', { name: 'Сообщение', exact: true })).toBeVisible();
}

test('coarse-pointer policy covers nested surfaces without clamping browser-level magnification', async ({ page, context }) => {
  await fixture(page);
  const client = await context.newCDPSession(page);
  expect(await page.evaluate(() => matchMedia('(hover: none) and (pointer: coarse)').matches)).toBe(true);
  expect(await page.evaluate(() => getComputedStyle(document.body).touchAction)).toBe('pan-x pan-y');
  const input = page.getByRole('textbox', { name: 'Сообщение', exact: true });
  expect(await input.evaluate((element) => getComputedStyle(element).touchAction)).toBe('pan-x pan-y');

  // Do not clamp author/page-scale metadata or intercept browser zoom commands.
  await client.send('Emulation.setPageScaleFactor', { pageScaleFactor: 2 });
  expect(await page.evaluate(() => visualViewport.scale)).toBeCloseTo(2, 2);
  await client.send('Emulation.setPageScaleFactor', { pageScaleFactor: 1 });
  await expect.poll(() => page.evaluate(() => visualViewport.scale)).toBeCloseTo(1, 2);

  await page.getByRole('button', { name: 'Модель: Авто', exact: true }).click();
  const search = page.getByRole('combobox', { name: 'Поиск модели' });
  expect(await search.evaluate((element) => getComputedStyle(element).touchAction)).toBe('pan-x pan-y');
  expect(await search.evaluate((element) => parseFloat(getComputedStyle(element).fontSize))).toBe(16);
});
