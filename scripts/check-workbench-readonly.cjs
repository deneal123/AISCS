/* Authenticated dev-only visual inspection. No provisioning, jobs or API writes. */
const { chromium } = require('playwright');
const fs = require('fs/promises');
const path = require('path');
let phase = 'configuration';

async function main() {
  const baseURL = process.env.E2E_BASE_URL || 'http://localhost:3001';
  const token = process.env.E2E_AUTH_TOKEN;
  const url = new URL(baseURL);
  if (!['localhost', '127.0.0.1'].includes(url.hostname) || url.port !== '3001' || !token) {
    throw new Error('authenticated_local_dev_required');
  }
  const output = path.resolve('.work/six-hour-ui-20261018/live-readonly');
  await fs.mkdir(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  let blockedWrites = 0;
  try {
    const context = await browser.newContext({ baseURL, serviceWorkers: 'block' });
    await context.addCookies([{ name: 'auth_token', value: token, url: baseURL }]);
    await context.addInitScript(value => {
      localStorage.setItem('telerag:isAuthenticated', 'true');
      localStorage.setItem('auth_token', value);
    }, token);
    await context.route('**/api/**', async route => {
      if (!['GET', 'HEAD', 'OPTIONS'].includes(route.request().method())) {
        blockedWrites += 1;
        await route.abort();
      } else await route.continue();
    });
    phase = 'owned_thread';
    const chats = await context.request.get('/api/chats/');
    if (!chats.ok()) throw new Error('dev_session_unavailable');
    const body = await chats.json();
    const thread = (body.threads || body.chats || [])[0];
    if (!thread?.thread_id) throw new Error('owned_thread_required');
    const page = await context.newPage();
    page.setDefaultTimeout(15000);
    // No stream can enqueue an agent request or resume a job in this inspection.
    await page.routeWebSocket('**/api/**', () => {});
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const screenshots = [];
    for (const width of [1440, 393]) {
      phase = `navigation_${width}`;
      await page.setViewportSize({ width, height: 900 });
      await page.goto(`/chat/${thread.thread_id}`, { waitUntil: 'domcontentloaded' });
      await page.getByRole('button', { name: 'Чат', exact: true }).waitFor({ state: 'visible' });
      phase = `library_${width}`;
      const library = page.getByRole('button', { name: 'Библиотека', exact: true });
      if (!await library.isVisible()) {
        const menu = page.getByRole('button', { name: 'Меню', exact: true });
        if (await menu.isVisible()) await menu.click();
        else await page.getByRole('button', { name: 'Переключить сайдбар', exact: true }).click();
      }
      await library.click();
      await page.getByTestId('workbench-library').waitFor({ state: 'visible' });
      const screenshot = path.join(output, `library-${width}.png`);
      await page.screenshot({ path: screenshot, animations: 'disabled' });
      screenshots.push(screenshot);
      if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) {
        throw new Error('live_horizontal_overflow');
      }
    }
    if (blockedWrites) throw new Error('unexpected_write_attempt_blocked');
    console.log(JSON.stringify({ screenshots, blocked_writes: blockedWrites, auth_artifact_written: false }));
  } finally { await browser.close(); }
}

main().catch(() => {
  // Browser/API errors can carry URLs or auth state. Report a bounded failure only.
  console.error(`readonly_dev_inspection_failed:${phase}`);
  process.exitCode = 1;
});
