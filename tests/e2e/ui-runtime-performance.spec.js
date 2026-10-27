const { test, expect } = require('@playwright/test');

test.skip(process.env.E2E_UI_PERFORMANCE !== '1', 'Opt-in comparable lab measurement; not field Core Web Vitals.');

async function installFixture(page) {
  await page.addInitScript(() => {
    localStorage.setItem('telerag:isAuthenticated', 'true');
    localStorage.setItem('auth_token', 'performance-fixture-token');
    window.__uiMetrics = { lcp: 0, longTasks: [] };
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) window.__uiMetrics.lcp = entry.startTime;
    }).observe({ type: 'largest-contentful-paint', buffered: true });
    new PerformanceObserver((list) => {
      window.__uiMetrics.longTasks.push(...list.getEntries().map((entry) => ({ start: entry.startTime, duration: entry.duration })));
    }).observe({ type: 'longtask', buffered: true });
  });
  await page.route('https://fonts.googleapis.com/**', (route) => route.fulfill({ contentType: 'text/css', body: '' }));
  await page.route('https://fonts.gstatic.com/**', (route) => route.abort());
  await page.route('**/static/fonts/**/*.woff2', (route) => route.abort());
  await page.routeWebSocket('**/api/**', () => {});
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    let json = {};
    if (path === '/api/profile/me') json = { id: 'performance-fixture', email: 'synthetic@example.test', permissions: [] };
    if (path === '/api/chats/') json = { chats: [{ thread_id: 'performance-fixture', title: 'Проверка производительности' }] };
    if (path === '/api/chats/performance-fixture') json = { messages: [{ id: 'fixture-message', sender: 'agent', content: 'Готов к работе. Это синтетический локальный материал для измерения интерфейса.' }] };
    if (path.endsWith('/trace')) json = { traces: {} };
    if (path.endsWith('/personas')) json = { personas: [] };
    if (path.endsWith('/models/catalog')) json = { models: [{ id: 'GigaChat-2', capabilities: ['tools'] }], providers: [] };
    if (path.endsWith('/transcription/config')) json = { enabled: false };
    await route.fulfill({ json });
  });
}

async function measureOpening(page, action) {
  await page.evaluate(() => {
    window.__uiFrames = [];
    window.__uiStart = performance.now();
    window.__uiRecording = true;
    let previous = window.__uiStart;
    const tick = (now) => {
      if (!window.__uiRecording) return;
      window.__uiFrames.push(now - previous);
      previous = now;
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
  await action();
  await expect(page.getByRole('dialog', { name: /^Настройки/ })).toBeVisible();
  await page.waitForTimeout(700); // Fixed animation observation window, not a readiness workaround.
  return page.evaluate(() => {
    window.__uiRecording = false;
    const frames = [...window.__uiFrames].sort((a, b) => a - b);
    return { elapsed: performance.now() - window.__uiStart, maxFrame: Math.max(...frames),
      p95Frame: frames[Math.floor(frames.length * 0.95)] || 0, frames: frames.length,
      longTasks: window.__uiMetrics.longTasks.filter((entry) => entry.start >= window.__uiStart).length };
  });
}

test('records cold LCP and cold/warm drawer frames under a fixed mobile CPU profile', async ({ browser }, info) => {
  test.setTimeout(120_000);
  const samples = [];
  for (let sample = 0; sample < 3; sample += 1) {
    const context = await browser.newContext({ viewport: { width: 393, height: 851 }, isMobile: true, hasTouch: true, serviceWorkers: 'block' });
    try {
      const page = await context.newPage();
      const cdp = await context.newCDPSession(page);
      await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 });
      await installFixture(page);
      await page.goto('/chat/performance-fixture');
      await expect(page.getByRole('button', { name: 'Настройки чата', exact: true })).toBeVisible();
      await page.waitForTimeout(4000); // Observe scheduled preloads and late LCP before first input.
      const initial = await page.evaluate(() => ({ ...window.__uiMetrics,
        jsResources: performance.getEntriesByType('resource').filter((entry) => entry.name.includes('/static/js/')).length }));
      const action = () => page.getByRole('button', { name: 'Настройки чата', exact: true }).click();
      const coldDrawer = await measureOpening(page, action);
      await page.getByRole('button', { name: 'Закрыть настройки', exact: true }).click();
      await expect(page.getByRole('dialog', { name: /^Настройки/ })).toBeHidden();
      const warmDrawer = await measureOpening(page, action);
      samples.push({ lcp: initial.lcp, initialLongTasks: initial.longTasks.length, jsResources: initial.jsResources, coldDrawer, warmDrawer });
    } finally { await context.close(); }
  }
  const result = { profile: 'compiled-mocked-mobile-cpu4-network-unthrottled-font-fallback', samples };
  console.log(JSON.stringify(result));
  await info.attach('ui-performance.json', { body: Buffer.from(JSON.stringify(result, null, 2)), contentType: 'application/json' });
});
