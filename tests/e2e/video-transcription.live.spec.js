const { test, expect } = require('@playwright/test');

// Opt-in real browser boundary: no routing/WS interception, no provider fallback.
test.use({ trace: 'off', video: 'off' });
test.setTimeout(180_000);

test('blocked YouTube transcription ends honestly after explicit consent', async ({ page, context }, info) => {
  test.skip(process.env.S38_STT_BLOCKED_LIVE !== '1');
  test.skip(info.project.name !== 'chromium');
  const token = process.env.E2E_AUTH_TOKEN;
  expect(Boolean(token)).toBeTruthy();
  await context.addCookies([{ name: 'auth_token', value: token,
    url: process.env.E2E_BASE_URL || 'http://localhost:3001' }]);
  await context.addInitScript((value) => {
    localStorage.setItem('telerag:isAuthenticated', JSON.stringify(true));
    localStorage.setItem('auth_token', value);
    localStorage.setItem('gpthub.chat.ui.settings', JSON.stringify({ memoryEnabled: false }));
  }, token);
  await page.setViewportSize({ width: 1440, height: 900 });
  const response = await page.request.post('/api/chats/', {
    data: { title: 'S38 STT source restriction acceptance' },
  });
  expect(response.status()).toBe(201);
  const thread = (await response.json()).thread_id;
  const frames = [];
  page.on('websocket', (socket) => socket.on('framereceived', ({ payload }) => {
    try { frames.push(JSON.parse(payload.toString())); } catch { /* UI rejects invalid frames */ }
  }));
  await page.goto(`/chat/${thread}`);
  await page.getByRole('button', { name: /Модель: Авто/ }).click();
  await page.getByRole('combobox', { name: 'Поиск модели' }).fill('GigaChat-2');
  await page.getByRole('option', { name: /\bGigaChat-2(?:\s|$)/ }).click();
  const request = 'https://www.youtube.com/watch?v=sXKnmgmbkoE Сделай транскрипцию видео';
  await page.getByPlaceholder('Напишите сообщение...').fill(request);
  await page.getByPlaceholder('Напишите сообщение...').press('Enter');
  const approve = page.getByRole('button', { name: /Использовать|Запустить/ }).first();
  await expect(approve).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole('button', { name: /Продолжить без этого|Не запускать/ }).first()).toBeVisible();
  expect(frames.some((frame) => frame.metadata?.generated_files?.length)).toBeFalsy();
  await approve.click();
  await expect.poll(async () => {
    if (await approve.isVisible() && await approve.isEnabled()) {
      await approve.click({ timeout: 1500 }).catch(async () => {
        if (await approve.isVisible()) throw new Error('confirmation_interaction_failed');
      });
    }
    return frames.some((frame) => frame.type === 'agent_reply'
      && frame.metadata?.execution_status === 'failed');
  }, { timeout: 120_000, intervals: [1000] }).toBeTruthy();
  const terminal = frames.find((frame) => frame.type === 'agent_reply'
    && frame.metadata?.execution_status === 'failed');
  expect(terminal.metadata.selected_model).toBe('GigaChat-2');
  expect(frames.some((frame) => frame.metadata?.generated_files?.length)).toBeFalsy();
  const history = await page.request.get(`/api/chats/${thread}`);
  expect(history.ok()).toBeTruthy();
  const messages = (await history.json()).messages;
  expect(messages.filter((message) => message.sender === 'user' && message.content === request)).toHaveLength(1);
  expect(messages.some((message) => message.metadata?.generated_files?.length)).toBeFalsy();
  await page.screenshot({ path: info.outputPath('source-unavailable.png'), fullPage: true });
  await page.reload();
  await expect(page.getByText(/Готовый файл (?:не объявлен созданным|не создан)/).first()).toBeVisible();
  console.log(JSON.stringify({ scenario: 'blocked_transcription', requestedModel: 'GigaChat-2',
    failedHonestly: true, generatedFiles: 0, duplicatedUserMessages: 0 }));
});

test('blocked transcription history reload keeps the accepted offer and no phantom file', async ({ page, context }, info) => {
  test.skip(process.env.S38_STT_RECOVERY_LIVE !== '1');
  test.skip(info.project.name !== 'chromium');
  const token = process.env.E2E_AUTH_TOKEN;
  const thread = process.env.S38_STT_RECOVERY_THREAD;
  expect(thread).toMatch(/^[a-f0-9-]{36}$/);
  await context.addCookies([{ name: 'auth_token', value: token,
    url: process.env.E2E_BASE_URL || 'http://localhost:3001' }]);
  await context.addInitScript((value) => {
    localStorage.setItem('telerag:isAuthenticated', JSON.stringify(true));
    localStorage.setItem('auth_token', value);
    localStorage.setItem('gpthub.chat.ui.settings', JSON.stringify({ memoryEnabled: false }));
  }, token);
  const response = await page.request.get(`/api/chats/${thread}`);
  expect(response.ok()).toBeTruthy();
  const messages = (await response.json()).messages;
  expect(messages.filter((message) => message.sender === 'user')).toHaveLength(1);
  const answer = messages.find((message) => message.sender === 'assistant'
    && message.metadata?.execution_status === 'failed');
  expect(answer).toBeTruthy();
  expect(answer.metadata.execution_status).toBe('failed');
  expect(answer.metadata.selected_model).toBe('GigaChat-2');
  const offer = messages.find((message) => message.metadata?.mode_offer);
  expect(offer.metadata.mode_offer.status).toBe('accepted');
  expect(messages.some((message) => message.metadata?.generated_files?.length)).toBeFalsy();
  await page.goto(`/chat/${thread}`);
  await expect(page.getByText(/Готовый файл (?:не объявлен созданным|не создан)/).first()).toBeVisible();
  await page.screenshot({ path: info.outputPath('source-unavailable-reload.png'), fullPage: true });
  await page.reload();
  await expect(page.getByText(/источник требует авторизации/).first()).toBeVisible();
  console.log(JSON.stringify({ scenario: 'blocked_transcription_reload', requestedModel: 'GigaChat-2',
    failedHonestly: true, generatedFiles: 0, duplicatedUserMessages: 0, newModelCalls: 0 }));
});
