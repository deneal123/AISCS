const fs = require('fs');
const crypto = require('crypto');
const { test, expect } = require('@playwright/test');

// Real backend/provider flow. No route or WebSocket interception/mocking.
test.use({ trace: 'off', video: 'off' });
test.setTimeout(240_000);

test('GigaChat video confirmation produces an owned downloadable note', async ({ page, context }, info) => {
  test.skip(process.env.S38_VIDEO_BROWSER_LIVE !== '1');
  test.skip(!['chromium', 'mobile-chrome'].includes(info.project.name));
  const token = process.env.E2E_AUTH_TOKEN;
  expect(Boolean(token)).toBeTruthy();
  const baseURL = process.env.E2E_BASE_URL || 'http://localhost:3001';
  await context.addCookies([{ name: 'auth_token', value: token, url: baseURL }]);
  await context.addInitScript((value) => {
    localStorage.setItem('telerag:isAuthenticated', JSON.stringify(true));
    localStorage.setItem('auth_token', value);
    // Background memory extraction has its own model policy; this acceptance
    // intentionally exercises only GigaChat and does not request that operation.
    localStorage.setItem('gpthub.chat.ui.settings', JSON.stringify({ memoryEnabled: false }));
  }, token);
  await page.setViewportSize(info.project.name === 'chromium'
    ? { width: 1440, height: 900 } : { width: 393, height: 851 });
  const response = await page.request.post('/api/chats/', {
    data: { title: 'S38 video browser acceptance' },
  }).catch(() => { throw new Error('thread_create_transport'); });
  expect(response.status()).toBe(201);
  const thread = (await response.json()).thread_id;
  console.log(`acceptance_thread=${thread}`);
  const received = [];
  page.on('requestfailed', (request) => {
    const target = new URL(request.url());
    console.log(JSON.stringify({ requestFailed: true,
      localTarget: ['localhost', '127.0.0.1'].includes(target.hostname),
      port: target.port, profileRequest: target.pathname.includes('profile'),
      networkCode: request.failure()?.errorText?.match(/ERR_[A-Z_]+/)?.[0] || 'unknown',
    }));
  });
  page.on('response', (result) => {
    if (new URL(result.url()).pathname.includes('profile')) {
      console.log(`profile_http=${result.status()}`);
    }
  });
  page.on('websocket', (socket) => socket.on('framereceived', ({ payload }) => {
    try { received.push(JSON.parse(payload.toString())); } catch { /* checked by UI validator */ }
  }));
  const catalogResponse = page.waitForResponse((response) =>
    new URL(response.url()).pathname === '/api/chats/models/catalog' && response.ok(),
  );
  await page.goto(`/chat/${thread}`);
  const catalog = await catalogResponse.then((response) => response.json());
  expect(catalog.models.some((model) => model.id === 'GigaChat-2')).toBeTruthy();
  await page.getByRole('button', { name: 'Работа', exact: true }).click();
  const passive = await page.request.get(`/api/chats/${thread}/work`)
    .catch(() => { throw new Error('work_snapshot_transport'); });
  expect(passive.ok()).toBeTruthy();
  expect((await passive.json()).workspace.state).toBe('absent');
  await page.getByRole('button', { name: 'Чат', exact: true }).click();
  console.log(JSON.stringify(await page.evaluate(() => ({
    authFlag: localStorage.getItem('telerag:isAuthenticated') === 'true',
    tokenPresent: Boolean(localStorage.getItem('auth_token')),
    cookiePresent: document.cookie.includes('auth_token='),
    redirectedToLogin: location.pathname === '/login',
  }))));
  await page.getByRole('button', { name: /Модель: Авто/ }).click();
  await page.getByRole('combobox', { name: 'Поиск модели' }).fill('GigaChat-2');
  const gigachatOption = page.getByRole('option', { name: /\bGigaChat-2(?:\s|$)/ });
  await expect(gigachatOption).toBeVisible();
  await gigachatOption.click();
  await expect(page.getByRole('button', { name: 'Модель: GigaChat-2', exact: true })).toBeVisible();
  const videoURL = process.env.S38_VIDEO_URL
    || (info.project.name === 'chromium' ? 'https://youtu.be/uTR9FdR3Ob0'
      : 'https://www.youtube.com/watch?v=uTR9FdR3Ob0');
  const request = `${videoURL} Нужно сделать полный конспект видео`;
  await page.getByPlaceholder('Напишите сообщение...').fill(request);
  await page.getByPlaceholder('Напишите сообщение...').press('Enter');
  const approve = page.getByRole('button', { name: /Использовать|Запустить/ }).first();
  await expect(approve).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole('button', { name: /Продолжить без этого|Не запускать/ }).first()).toBeVisible();
  expect(received.some((frame) => frame.metadata?.generated_files?.length)).toBeFalsy();
  await approve.click();
  // A whole-run estimate and tool-specific offer can be distinct explicit gates.
  await expect.poll(async () => {
    if (received.some((frame) => frame.type === 'error')) throw new Error('video_terminal_error');
    if (await approve.isVisible() && await approve.isEnabled()) {
      // Acceptance can remove this control between visibility and click.
      // Only tolerate that DOM race, never a still-present failed interaction.
      await approve.click({ timeout: 1500 }).catch(async () => {
        if (await approve.isVisible()) throw new Error('confirmation_interaction_failed');
      });
    }
    return received.some((frame) => frame.type === 'agent_reply'
      && frame.metadata?.generated_files?.length);
  }, { timeout: 180_000, intervals: [1000] }).toBeTruthy();
  const terminal = received.find((frame) => frame.type === 'agent_reply'
    && frame.metadata?.generated_files?.length);
  expect(terminal.metadata.selected_model).toBe('GigaChat-2');
  expect(terminal.metadata.execution_status).toBe('completed');
  const file = terminal.metadata.generated_files.find((item) => item.filename.endsWith('.md'));
  expect(file).toBeTruthy();
  const downloadResponse = await page.request.get(`/api/service/files/v1/${file.file_id}/download`)
    .catch(() => { throw new Error('download_transport'); });
  expect(downloadResponse.ok()).toBeTruthy();
  const bytes = await downloadResponse.body();
  expect(bytes.length).toBeGreaterThan(1000);
  const text = bytes.toString('utf8');
  expect(text).toContain('Конспект');
  expect(text).not.toMatch(/мне необходим сам контент|страница содержит лишь служебную/i);
  fs.writeFileSync(info.outputPath('video-notes.md'), bytes);
  const tree = await page.request.get(`/api/chats/${thread}/workspace`)
    .catch(() => { throw new Error('workspace_tree_transport'); });
  expect(tree.ok()).toBeTruthy();
  const entry = (await tree.json()).entries.find((row) => row.path.endsWith(file.filename));
  expect(entry).toBeTruthy();
  const folder = entry.path.slice(0, entry.path.lastIndexOf('/'));
  for (const artifact of ['transcript.md', 'authoring.json']) {
    const source = await page.request.post(`/api/chats/${thread}/workspace/file`, {
      data: { path: `${folder}/${artifact}` },
    }).catch(() => { throw new Error('source_review_transport'); });
    expect(source.ok()).toBeTruthy();
    fs.writeFileSync(info.outputPath(artifact), (await source.json()).content);
  }
  console.log(JSON.stringify({ viewport: info.project.name, provider: 'gigachat',
    model: 'GigaChat-2', bytes: bytes.length,
    sha256: crypto.createHash('sha256').update(bytes).digest('hex') }));
  await page.screenshot({ path: info.outputPath('completed.png'), fullPage: true });
  const trace = page.getByRole('button', { name: 'Ход работы', exact: true });
  if (await trace.isVisible()) await trace.click();
  await page.getByText(file.filename, { exact: true }).first().scrollIntoViewIfNeeded();
  const downloadEvent = page.waitForEvent('download');
  await page.getByRole('link', { name: file.filename, exact: true }).click();
  const uiDownload = await downloadEvent;
  expect(await uiDownload.failure()).toBeNull();
  await uiDownload.saveAs(info.outputPath('ui-video-notes.md'));
  const uiBytes = fs.readFileSync(info.outputPath('ui-video-notes.md'));
  expect(crypto.createHash('sha256').update(uiBytes).digest('hex'))
    .toBe(crypto.createHash('sha256').update(bytes).digest('hex'));
  await page.screenshot({ path: info.outputPath('download-card.png'), fullPage: true });
  await page.reload();
  await expect(page.getByText(file.filename, { exact: true }).first()).toBeVisible();
  await page.getByRole('button', { name: 'Работа', exact: true }).click();
  await expect(page).toHaveURL(/surface=work/);
  const libraryTab = page.getByRole('tab', { name: /Библиотека/ });
  await libraryTab.or(page.getByRole('button', { name: /Библиотека/ })).first().click();
  await expect(page.getByText(file.filename, { exact: true }).first()).toBeVisible();
  await page.screenshot({ path: info.outputPath('work-library.png'), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  // Keep the isolated thread for manual review, including failure recovery evidence.
});

test('an existing delivered note remains available in Work Library', async ({ page, context }, info) => {
  test.skip(process.env.S38_VIDEO_BROWSER_LIVE !== '1' || !process.env.S38_EXISTING_THREAD);
  test.skip(!['chromium', 'mobile-chrome'].includes(info.project.name));
  const thread = process.env.S38_EXISTING_THREAD;
  expect(thread).toMatch(/^[0-9a-f-]{36}$/);
  const token = process.env.E2E_AUTH_TOKEN;
  await context.addCookies([{ name: 'auth_token', value: token,
    url: process.env.E2E_BASE_URL || 'http://localhost:3001' }]);
  await context.addInitScript((value) => {
    localStorage.setItem('telerag:isAuthenticated', JSON.stringify(true));
    localStorage.setItem('auth_token', value);
  }, token);
  await page.setViewportSize(info.project.name === 'chromium'
    ? { width: 1440, height: 900 } : { width: 393, height: 851 });
  const response = await page.request.get(`/api/chats/${thread}`)
    .catch(() => { throw new Error('history_transport'); });
  expect(response.ok()).toBeTruthy();
  const messages = (await response.json()).messages;
  const file = messages.flatMap((item) => item.metadata?.generated_files || [])
    .find((item) => item.filename.endsWith('.md'));
  expect(file).toBeTruthy();
  await page.goto(`/chat/${thread}?surface=work`);
  await page.getByRole('tab', { name: /Библиотека/ })
    .or(page.getByRole('button', { name: /Библиотека/ })).first().click();
  await expect(page.getByText(file.filename, { exact: true }).first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: info.outputPath('work-library.png'), fullPage: true });
});
