/* Explicit native dev onboarding acceptance; never sends an agent message. */
const { chromium, expect } = require('@playwright/test');
const fs = require('fs/promises');
const path = require('path');
let phase = 'configuration';

async function main() {
  const baseURL = process.env.E2E_BASE_URL || 'http://localhost:3001';
  const token = process.env.E2E_AUTH_TOKEN;
  const endpoint = new URL(baseURL);
  if (process.env.E2E_LIVE_PDF_PREPARATION !== '1' || !token
    || !['localhost', '127.0.0.1'].includes(endpoint.hostname) || endpoint.port !== '3001') {
    throw new Error('explicit_authenticated_dev_required');
  }
  const browser = await chromium.launch({ headless: true });
  const output = path.resolve('.work/six-hour-ui-20261018/native-pdf-onboarding');
  await fs.mkdir(output, { recursive: true });
  let threadId;
  let activePage;
  let blockedWrites = 0;
  const blockedPaths = [];
  const preparations = [];
  let droppedCreateReplies = 0;
  let sourceWrites = 0;
  try {
    const context = await browser.newContext({ baseURL, serviceWorkers: 'block' });
    await context.addCookies([{ name: 'auth_token', value: token, url: baseURL }]);
    await context.addInitScript(value => {
      localStorage.setItem('telerag:isAuthenticated', 'true');
      localStorage.setItem('auth_token', value);
    }, token);
    phase = 'create_test_thread';
    if (process.env.E2E_PDF_THREAD_ID) {
      threadId = process.env.E2E_PDF_THREAD_ID;
      if (!/^[a-f0-9-]{36}$/.test(threadId)) throw new Error('invalid_test_thread');
      const owned = await context.request.get(`/api/chats/${threadId}`);
      if (!owned.ok()) throw new Error('owned_test_thread_required');
    } else {
      const created = await context.request.post('/api/chats/', { data: { title: 'QA PDF auto-onboarding' } });
      if (!created.ok()) throw new Error('test_thread_unavailable');
      threadId = (await created.json()).thread_id;
    }
    if (!/^[a-f0-9-]{36}$/.test(threadId || '')) throw new Error('invalid_test_thread');
    const page = await context.newPage();
    activePage = page;
    const createPresentation = process.env.E2E_CREATE_PRESENTATION === '1';
    const dropCreateAck = createPresentation && process.env.E2E_LOSE_CREATE_ACK === '1';
    const checkFormatting = process.env.E2E_CHECK_FORMATTING === '1';
    page.setDefaultTimeout(30000);
    await page.routeWebSocket('**/api/**', () => {});
    await page.route('**/api/**', async route => {
      const request = route.request();
      const pathname = new URL(request.url()).pathname;
      const preparation = request.method() === 'POST'
        && pathname === `/api/chats/${threadId}/work/pdf/prepare`;
      const sourceRead = request.method() === 'POST' && [
        `/api/chats/${threadId}/workspace/documents/authoring`,
        `/api/chats/${threadId}/workspace/documents/status`,
      ].includes(pathname);
      const creation = createPresentation && request.method() === 'POST' && [
        `/api/chats/${threadId}/workspace/leases/acquire`,
        `/api/chats/${threadId}/workspace/leases/release`,
        `/api/chats/${threadId}/workspace/documents`,
        `/api/chats/${threadId}/workspace/documents/authoring/edit`,
      ].includes(pathname);
      if (dropCreateAck && request.method() === 'POST'
        && pathname === `/api/chats/${threadId}/workspace/documents` && !droppedCreateReplies) {
        const accepted = await route.fetch({ maxRedirects: 0 });
        if (!accepted.ok()) throw new Error('create_not_accepted');
        droppedCreateReplies += 1;
        await route.abort();
        return;
      }
      if (request.method() === 'POST'
        && pathname === `/api/chats/${threadId}/workspace/documents/authoring/edit`) sourceWrites += 1;
      const formatting = checkFormatting && request.method() === 'POST' && [
        `/api/chats/${threadId}/workspace/leases/acquire`,
        `/api/chats/${threadId}/workspace/leases/release`,
        `/api/chats/${threadId}/workspace/documents/profile`,
      ].includes(pathname);
      if (['GET', 'HEAD', 'OPTIONS'].includes(request.method()) || preparation || sourceRead || creation || formatting) {
        await route.continue();
      } else {
        blockedWrites += 1;
        blockedPaths.push(pathname.replace(threadId, ':thread'));
        await route.abort();
      }
    });
    const pendingResponses = new Set();
    page.on('response', response => {
      if (new URL(response.url()).pathname !== `/api/chats/${threadId}/work/pdf/prepare`) return;
      const pending = (async () => {
        const body = await response.json().catch(() => ({}));
        preparations.push({ status: response.status(), state: body.state || 'unknown',
          code: body.error?.code || null });
      })();
      pendingResponses.add(pending);
      void pending.finally(() => pendingResponses.delete(pending));
    });
    const widths = process.env.E2E_MOBILE_ONLY === '1' ? [393]
      : createPresentation || checkFormatting ? [1440] : [1440, 393];
    for (const width of widths) {
      phase = `entry_${width}`;
      await page.setViewportSize({ width, height: 900 });
      await page.goto(`/chat/${threadId}?surface=pdf`, { waitUntil: 'domcontentloaded' });
      await expect(page.getByTestId('pdf-studio')).toBeVisible();
      await expect(page.getByRole('textbox', { name: 'Название документа', exact: true }))
        .toHaveValue('Новый документ', { timeout: 60000 });
      if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) {
        throw new Error('horizontal_overflow');
      }
      await page.screenshot({ path: path.join(output, `pdf-${width}.png`), animations: 'disabled' });
    }
    if (createPresentation) {
      phase = 'new_presentation';
      await page.getByRole('button', { name: 'Новый документ', exact: true }).click();
      const dialog = page.getByRole('dialog', { name: 'Новый документ', exact: true });
      const format = dialog.getByRole('combobox', { name: 'Формат нового документа', exact: true });
      await format.focus(); await format.press('ArrowDown');
      await dialog.getByRole('option', { name: /презентац/i }).first().click();
      await dialog.getByRole('button', { name: 'Создать документ', exact: true }).click();
      await expect(dialog).toBeHidden({ timeout: 60000 });
      if (dropCreateAck) {
        await expect(page.getByRole('button', { name: 'Открыть исходник', exact: true })).toBeVisible();
        await expect(page.getByText('Документ найден после проверки', { exact: true })).toBeVisible();
        await expect(page.getByRole('button', { name: 'Новое содержание без ИИ', exact: true })).toBeEnabled();
        if (droppedCreateReplies !== 1 || sourceWrites !== 0) throw new Error('create_replay_write');
      } else {
        await expect(page.getByRole('textbox', { name: 'Название документа', exact: true }))
          .toHaveValue('Новая презентация', { timeout: 30000 });
      }
      await page.screenshot({ path: path.join(output, dropCreateAck ? 'recovered-presentation.png' : 'new-presentation.png'), animations: 'disabled' });
    }
    if (checkFormatting) {
      phase = 'apply_formatting';
      await page.getByRole('button', { name: 'Оформление', exact: true }).click();
      let panel = page.getByRole('dialog');
      await expect.poll(async () => {
        const bounds = await panel.boundingBox();
        return bounds ? Math.abs(bounds.x + bounds.width - 1440) < 1 : false;
      }).toBe(true);
      const language = panel.getByRole('combobox', { name: 'Язык PDF-документа', exact: true });
      const nextLanguage = await panel.getByText('English', { exact: true }).count() ? 'Русский' : 'English';
      await language.focus(); await language.press('ArrowDown');
      await panel.getByRole('option', { name: nextLanguage, exact: true }).click();
      const apply = panel.getByRole('button', { name: 'Применить настройки', exact: true });
      await expect(apply).toBeEnabled(); await apply.click();
      await expect(apply).toBeDisabled({ timeout: 30000 });
      await panel.getByRole('button', { name: 'Закрыть панель документа' }).click();
      await page.reload({ waitUntil: 'domcontentloaded' });
      await expect(page.getByRole('textbox', { name: 'Название документа', exact: true }))
        .toHaveValue('Новый документ', { timeout: 30000 });
      await page.getByRole('button', { name: 'Оформление', exact: true }).click();
      panel = page.getByRole('dialog');
      await expect(panel.getByText(nextLanguage, { exact: true })).toBeVisible();
      await expect.poll(async () => {
        const bounds = await panel.boundingBox();
        return bounds ? Math.abs(bounds.x + bounds.width - 1440) < 1 : false;
      }).toBe(true);
      await page.screenshot({ path: path.join(output, 'applied-formatting.png'), animations: 'disabled' });
    }
    await Promise.all([...pendingResponses]);
    if (blockedWrites || (!process.env.E2E_PDF_THREAD_ID && !preparations.length)
      || preparations.some(item => item.state !== 'ready')) {
      throw new Error('preparation_unconfirmed');
    }
    console.log(JSON.stringify({ thread_id: threadId, preparations, blocked_writes: blockedWrites,
      agent_messages: 0, source_writes: sourceWrites, dropped_create_replies: droppedCreateReplies,
      auth_artifact_written: false, fixture_retained: true }));
  } catch {
    if (activePage) await activePage.screenshot({ path: path.join(output, 'failure.png'), timeout: 3000 }).catch(() => {});
    console.error(JSON.stringify({ failure: 'native_pdf_onboarding_failed', phase,
      thread_id: threadId || null, preparations, blocked_writes: blockedWrites, blocked_paths: blockedPaths }));
    process.exitCode = 1;
  } finally { await browser.close(); }
}

main().catch(() => {
  console.error(`native_pdf_onboarding_failed:${phase}`);
  process.exitCode = 1;
});
