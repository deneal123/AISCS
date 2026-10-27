/* Native dev UI acceptance in an existing labelled QA scope; never sends an agent message. */
const { chromium, expect } = require('@playwright/test');
const path = require('path');
const fs = require('fs/promises');
let phase = 'configuration';

async function main() {
  const baseURL = process.env.E2E_BASE_URL || 'http://localhost:3001';
  const token = process.env.E2E_AUTH_TOKEN;
  const threadId = process.env.E2E_IDE_SAVED_THREAD;
  const url = new URL(baseURL);
  if (process.env.E2E_LIVE_IDE_SAVED_PROJECTS !== '1' || !token || !/^[a-f0-9-]{36}$/.test(threadId || '')
    || !['localhost', '127.0.0.1'].includes(url.hostname) || url.port !== '3001') throw Error('explicit_dev_qa_required');
  const browser = await chromium.launch({ headless: true });
  let saves = 0; let blocked = 0;
  try {
    const context = await browser.newContext({ baseURL, serviceWorkers: 'block' });
    await context.addCookies([{ name: 'auth_token', value: token, url: baseURL }]);
    await context.addInitScript(value => {
      localStorage.setItem('telerag:isAuthenticated', 'true'); localStorage.setItem('auth_token', value);
    }, token);
    phase = 'qa_scope';
    const owned = await context.request.get('/api/chats/');
    const catalog = owned.ok() ? await owned.json() : {};
    const chats = catalog.threads;
    if (!chats?.some(item => item.thread_id === threadId && item.title?.startsWith('QA IDE'))) throw Error('labelled_owned_qa_required');
    const repositories = await context.request.get(`/api/chats/${threadId}/ide/repositories`);
    const repository = (await repositories.json()).items?.[0];
    if (!repositories.ok() || !repository) throw Error('qa_repository_required');
    const previous = await context.request.get(`/api/chats/${threadId}/ide/repositories/${repository.repository_id}/checkpoints`);
    if (!previous.ok()) throw Error('qa_history_required');
    const versions = Math.min((await previous.json()).items.length + 1, 11);
    const page = await context.newPage(); page.setDefaultTimeout(30000);
    await page.routeWebSocket('**/api/**', () => {});
    await page.route('**/api/**', async route => {
      const request = route.request(); const pathname = new URL(request.url()).pathname;
      const inScope = pathname.startsWith(`/api/chats/${threadId}/ide/`);
      const write = request.method() === 'POST';
      const safe = inScope && write && (pathname.endsWith('/ide/prepare') || /\/files\/(tree|read)$/.test(pathname)
        || pathname.endsWith('/checkpoints') || (pathname.endsWith('/git') && request.postDataJSON().operation === 'status'));
      if (safe && pathname.endsWith('/checkpoints')) saves += 1;
      if (['GET', 'HEAD', 'OPTIONS'].includes(request.method()) || safe) await route.continue();
      else { blocked += 1; await route.abort(); }
    });
    phase = 'entry';
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/chat/${threadId}?surface=work`, { waitUntil: 'domcontentloaded' });
    const save = page.getByRole('button', { name: 'Сохранить проект', exact: true });
    await expect(save).toBeEnabled({ timeout: 60000 });
    phase = 'save';
    await save.click(); await expect(save).toBeEnabled({ timeout: 60000 });
    await expect.poll(() => saves).toBe(1);
    await page.getByRole('button', { name: 'История проекта', exact: true }).click();
    phase = 'history';
    const dialog = page.getByRole('dialog', { name: /История проекта/ });
    await expect(dialog.getByRole('listitem')).toHaveCount(versions);
    const output = path.resolve('.work/save-restore-native'); await fs.mkdir(output, { recursive: true });
    await page.screenshot({ path: path.join(output, 'ide-history-desktop.png') });
    await page.keyboard.press('Escape');
    await page.setViewportSize({ width: 320, height: 740 });
    await page.getByRole('button', { name: 'История проекта', exact: true }).click();
    await expect(dialog).toBeVisible();
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw Error('overflow');
    await page.screenshot({ path: path.join(output, 'ide-history-320.png') });
    if (blocked) throw Error('unexpected_write');
    console.log(JSON.stringify({ native_ui: 'passed', saves, history_versions: versions, widths: [1440, 320], blocked_writes: blocked, agent_messages: 0 }));
  } finally { await browser.close(); }
}
main().catch(() => { console.error(`native_ide_saved_projects_ui_failed:${phase}`); process.exitCode = 1; });
