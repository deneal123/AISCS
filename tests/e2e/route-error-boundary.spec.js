const { test, expect } = require('@playwright/test');
const axe = require('axe-core');

test.use({ serviceWorkers: 'block' });
const THREAD = 'chunk-failure-fixture';

async function fixture(page) {
  let messages = 0;
  await page.addInitScript(() => {
    localStorage.setItem('telerag:isAuthenticated', 'true');
    localStorage.setItem('auth_token', 'route-error-fixture-token');
  });
  await page.routeWebSocket('**/api/**', (socket) => {
    socket.onMessage((raw) => { if (JSON.parse(raw).type === 'message') messages += 1; });
  });
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    let json = {};
    if (path === '/api/profile/me') json = { id: 'fixture-user', email: 'route@example.test', permissions: [] };
    if (path === '/api/chats/') json = { chats: [{ thread_id: THREAD, title: 'Проверка восстановления' }] };
    if (path === `/api/chats/${THREAD}`) json = { messages: [] };
    if (path.endsWith('/trace')) json = { traces: {} };
    if (path.endsWith('/models/catalog')) json = { models: [], providers: [] };
    if (path.endsWith('/personas')) json = { personas: [] };
    if (path.endsWith('/transcription/config')) json = { enabled: false };
    await route.fulfill({ json });
  });
  return () => messages;
}

test('failed chat chunk preserves navigation and recovers only after explicit reload', async ({ page }, info) => {
  const messages = await fixture(page);
  let navigations = 0;
  page.on('request', (request) => {
    if (request.isNavigationRequest() && request.frame() === page.mainFrame()) navigations += 1;
  });
  let fail = true;
  let blocked = 0;
  await page.route('**/static/js/**', async (route) => {
    if (fail && new URL(route.request().url()).pathname.includes('/route-chat')) {
      blocked += 1;
      await route.abort('failed');
    } else await route.continue();
  });
  await page.goto(`/chat/${THREAD}`);
  await expect(page.getByRole('heading', { name: 'Не удалось открыть страницу', exact: true })).toBeVisible();
  expect(blocked).toBeGreaterThan(0);
  await expect(page.getByRole('banner')).toBeVisible();
  await expect(page.getByRole('link', { name: 'На главную', exact: true })).toHaveAttribute('href', '/');
  await expect(page).toHaveTitle('Ошибка страницы — GPTHub');
  expect(navigations).toBe(1);
  expect(messages()).toBe(0);
  await expect(page.locator('body')).not.toContainText('Unexpected Application Error');
  await expect(page.locator('body')).not.toContainText('ChunkLoadError');
  await expect(page.getByRole('button', { name: 'Попробовать снова', exact: true })).toHaveCount(0);
  await page.addScriptTag({ content: axe.source });
  const failures = await page.evaluate(async () => {
    const report = await window.axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'] } });
    return report.violations.filter((entry) => ['serious', 'critical'].includes(entry.impact)).map((entry) => entry.id);
  });
  expect(failures).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath('route-error-safe.png') });
  fail = false;
  await page.getByRole('button', { name: 'Обновить страницу', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'Сообщение', exact: true })).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/chat/${THREAD}$`));
  await expect(page.getByRole('heading', { name: 'Не удалось открыть страницу', exact: true })).toHaveCount(0);
  expect(messages()).toBe(0);
});
