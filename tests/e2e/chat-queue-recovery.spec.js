const { test, expect } = require('@playwright/test');
test.use({ serviceWorkers: 'block' });
const THREAD = 'queue-recovery-fixture';

async function fixture(page, { historyStatus = 200 } = {}) {
  // Transport acceptance must not depend on an external font CDN.
  await page.route('https://fonts.googleapis.com/**', (route) => route.fulfill({ contentType: 'text/css', body: '' }));
  await page.route('https://fonts.gstatic.com/**', (route) => route.abort());
  await page.route('**/static/fonts/**/*.woff2', (route) => route.abort());
  await page.addInitScript(() => {
    localStorage.setItem('telerag:isAuthenticated', 'true');
    localStorage.setItem('auth_token', 'queue-fixture-token');
    const NativeSocket = window.WebSocket;
    window.__queueFixture = { sockets: [], attempts: 0, messages: [], fail: false };
    window.WebSocket = class {
      static OPEN = 1;
      static CONNECTING = 0;
      static CLOSED = 3;
      constructor(url, protocols) {
        if (!new URL(url, location.href).pathname.startsWith('/api/')) return new NativeSocket(url, protocols);
        this.readyState = 0;
        this.url = url;
        if (new URL(url, location.href).pathname.includes('/chats/')) window.__queueFixture.sockets.push(this);
        else setTimeout(() => { this.readyState = 1; this.onopen?.(); }, 0);
      }
      send(raw) {
        const message = JSON.parse(raw);
        if (message.type !== 'message') return;
        window.__queueFixture.attempts += 1;
        if (window.__queueFixture.fail) throw new Error('PRIVATE_SEND_FIXTURE');
        window.__queueFixture.messages.push({ ...message, socket_url: this.url });
      }
      close() { this.readyState = 3; this.onclose?.({ code: 1000 }); }
    };
  });
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    let json = {};
    if (path === '/api/profile/me') json = { id: 'queue-user', email: 'queue@example.test', permissions: [] };
    if (path === '/api/chats/') json = { chats: [
      { thread_id: THREAD, title: 'Очередь запроса' }, { thread_id: 'other-queue-fixture', title: 'Другой тред' },
    ] };
    if (path === `/api/chats/${THREAD}` && historyStatus !== 200) {
      return route.fulfill({ status: historyStatus, json: { detail: 'Thread not found' } });
    }
    if (path === `/api/chats/${THREAD}` || path === '/api/chats/other-queue-fixture') json = { messages: [] };
    if (path.endsWith('/trace')) json = { traces: {} };
    if (path.endsWith('/models/catalog')) json = { models: [], providers: [] };
    if (path.endsWith('/personas')) json = { personas: [] };
    if (path.endsWith('/transcription/config')) json = { enabled: false };
    await route.fulfill({ json });
  });
  await page.goto(`/chat/${THREAD}`, { waitUntil: 'domcontentloaded' });
  await expect.poll(() => page.evaluate(() => window.__queueFixture.sockets.length)).toBe(1);
}

async function openLatest(page) {
  await page.evaluate(() => {
    const socket = window.__queueFixture.sockets.at(-1);
    socket.readyState = 1;
    socket.onopen();
  });
}

test('policy refusal after history404 stops reconnect while preserving the draft', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 393, height: 852 });
  await fixture(page, { historyStatus: 404 });
  await openLatest(page);
  const input = page.getByRole('textbox', { name: 'Сообщение', exact: true });
  await input.fill('Сохранить мой черновик');
  await page.evaluate(() => {
    const socket = window.__queueFixture.sockets.at(-1);
    socket.readyState = 3;
    socket.onclose({ code: 1008, reason: 'PRIVATE_THREAD_OWNER_DETAIL' });
  });
  await expect(page.getByText('Не удалось подтвердить доступ.', { exact: true }).first()).toBeVisible();
  await expect(input).toHaveValue('Сохранить мой черновик');
  await expect(page.locator('body')).not.toContainText('PRIVATE_THREAD_OWNER_DETAIL');
  // Полный retry-таймер проверяется fake clock в unit; браузер проверяет тот же
  // error owner и отсутствие первого автоматического reconnect.
  await page.waitForTimeout(1500);
  expect(await page.evaluate(() => window.__queueFixture.sockets.length)).toBe(1);
  expect(await page.evaluate(() => window.__queueFixture.attempts)).toBe(0);
  await page.screenshot({ path: testInfo.outputPath('policy-denial-mobile.png') });
});

test('Stop withdraws unsent work before job acknowledgement', async ({ page }) => {
  await fixture(page);
  await page.getByRole('textbox', { name: 'Сообщение', exact: true }).fill('Синтетический запрос');
  await page.getByRole('button', { name: 'Отправить', exact: true }).click();
  await page.getByRole('button', { name: 'Остановить генерацию', exact: true }).click();
  await openLatest(page);
  expect(await page.evaluate(() => window.__queueFixture.attempts)).toBe(0);
  await expect(page.getByRole('button', { name: 'Остановить генерацию', exact: true })).toHaveCount(0);
});

test('retired socket events cannot send or interrupt the new thread queue', async ({ page }) => {
  await fixture(page);
  await openLatest(page);
  await page.evaluate(() => window.__queueFixture.sockets[0].onmessage({
    data: JSON.stringify({ type: 'heartbeat', id: 'old-fixture-cursor' }),
  }));
  const destination = page.getByRole('button', { name: 'Другой тред', exact: true });
  if (!await destination.isVisible()) await page.getByRole('button', { name: 'Меню', exact: true }).click();
  await destination.click();
  await expect(page).toHaveURL(/\/chat\/other-queue-fixture$/);
  await expect.poll(() => page.evaluate(() => window.__queueFixture.sockets.length)).toBe(2);
  await page.getByRole('textbox', { name: 'Сообщение', exact: true }).fill('NEW_THREAD_FIXTURE');
  await page.getByRole('button', { name: 'Отправить', exact: true }).click();
  await page.evaluate(() => {
    const old = window.__queueFixture.sockets[0];
    old.readyState = 1;
    old.onopen();
    old.onmessage({ data: JSON.stringify({ type: 'stream_chunk', data: 'OLD_THREAD_PRIVATE' }) });
    old.onerror();
    old.onclose({ code: 1006 });
  });
  expect(await page.evaluate(() => window.__queueFixture.attempts)).toBe(0);
  await expect(page.getByRole('button', { name: 'Остановить генерацию', exact: true })).toBeVisible();
  await expect(page.locator('body')).not.toContainText('OLD_THREAD_PRIVATE');
  await openLatest(page);
  const messages = await page.evaluate(() => window.__queueFixture.messages);
  expect(messages).toHaveLength(1);
  expect(messages[0].text).toBe('NEW_THREAD_FIXTURE');
  expect(messages[0].socket_url).toContain('/other-queue-fixture/ws');
  expect(messages[0].socket_url).not.toContain('last_id=');
});

test('accepted work keeps Stop through connection loss and finishes from replay without resending', async ({ page }) => {
  await fixture(page);
  await openLatest(page);
  await page.getByRole('textbox', { name: 'Сообщение', exact: true }).fill('Синтетическое принятое задание');
  await page.getByRole('button', { name: 'Отправить', exact: true }).click();
  await page.evaluate(() => {
    const socket = window.__queueFixture.sockets.at(-1);
    socket.onmessage({ data: JSON.stringify({ type: 'job_created', job_id: 'accepted-job', celery_task_id: 'fixture-task' }) });
    socket.onmessage({ data: JSON.stringify({ type: 'stream_chunk', job_id: 'accepted-job', data: 'Первая часть ' }) });
    socket.onmessage({ data: JSON.stringify({ type: 'agent_complete', job_id: 'accepted-job' }) });
    socket.onerror();
    socket.readyState = 3;
    socket.onclose({ code: 1006 });
  });
  await expect(page.getByRole('button', { name: 'Остановить генерацию', exact: true })).toBeVisible();
  await expect.poll(() => page.evaluate(() => window.__queueFixture.sockets.length)).toBe(2);
  await openLatest(page);
  await page.evaluate(() => {
    const socket = window.__queueFixture.sockets.at(-1);
    socket.onmessage({ data: JSON.stringify({ type: 'replay', data: {
      type: 'stream_chunk', job_id: 'accepted-job', data: 'Вторая часть',
    } }) });
    socket.onmessage({ data: JSON.stringify({ type: 'agent_reply', job_id: 'accepted-job',
      reply: 'Первая часть Вторая часть', metadata: { execution_status: 'completed' } }) });
  });
  await expect(page.getByText('Первая часть Вторая часть', { exact: true })).toHaveCount(1);
  await expect(page.getByText('Первая часть', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Остановить генерацию', exact: true })).toHaveCount(0);
  expect(await page.evaluate(() => window.__queueFixture.attempts)).toBe(1);
});

test('a late final answer after Stop preserves the next composer draft', async ({ page }) => {
  await fixture(page);
  await openLatest(page);
  const input = page.getByRole('textbox', { name: 'Сообщение', exact: true });
  await input.fill('Синтетическое задание для отмены');
  await page.getByRole('button', { name: 'Отправить', exact: true }).click();
  await page.evaluate(() => window.__queueFixture.sockets.at(-1).onmessage({ data: JSON.stringify({
    type: 'job_created', job_id: 'stopped-job', celery_task_id: 'stopped-task',
  }) }));
  await page.getByRole('button', { name: 'Остановить генерацию', exact: true }).click();
  await input.fill('Сохранить новый черновик');
  await page.evaluate(() => window.__queueFixture.sockets.at(-1).onmessage({ data: JSON.stringify({
    type: 'agent_reply', job_id: 'stopped-job', reply: 'Запоздалый доступный ответ',
  }) }));
  await expect(page.getByText('Запоздалый доступный ответ', { exact: true })).toHaveCount(1);
  await expect(input).toHaveValue('Сохранить новый черновик');
  expect(await page.evaluate(() => window.__queueFixture.attempts)).toBe(1);
});

test('replayed acknowledgements cannot reopen a final answer or replace newer work', async ({ page }) => {
  await fixture(page);
  await openLatest(page);
  const input = page.getByRole('textbox', { name: 'Сообщение', exact: true });
  const send = page.getByRole('button', { name: 'Отправить', exact: true });
  const stop = page.getByRole('button', { name: 'Остановить генерацию', exact: true });
  await input.fill('Первое синтетическое задание');
  await send.click();
  await page.evaluate(() => {
    const socket = window.__queueFixture.sockets.at(-1);
    socket.onmessage({ data: JSON.stringify({ type: 'job_created', job_id: 'finished-job' }) });
    socket.onmessage({ data: JSON.stringify({ type: 'agent_reply', job_id: 'finished-job', reply: 'Первый готовый ответ' }) });
  });
  await expect(page.getByText('Первый готовый ответ', { exact: true })).toHaveCount(1);
  await page.evaluate(() => {
    const socket = window.__queueFixture.sockets.at(-1);
    socket.onmessage({ data: JSON.stringify({ type: 'job_created', job_id: 'finished-job' }) });
    socket.onmessage({ data: JSON.stringify({ type: 'agent_reply', job_id: 'finished-job', reply: 'Первый готовый ответ' }) });
  });
  await expect(stop).toHaveCount(0);
  await expect(page.getByText('Первый готовый ответ', { exact: true })).toHaveCount(1);
  await input.fill('Второе синтетическое задание');
  await send.click();
  await page.evaluate(() => {
    const socket = window.__queueFixture.sockets.at(-1);
    socket.onmessage({ data: JSON.stringify({ type: 'job_created', job_id: 'new-job' }) });
    socket.onmessage({ data: JSON.stringify({ type: 'job_created', job_id: 'finished-job' }) });
    socket.onmessage({ data: JSON.stringify({ type: 'agent_reply', job_id: 'finished-job', reply: 'Первый готовый ответ' }) });
    socket.onmessage({ data: JSON.stringify({ type: 'stream_chunk', job_id: 'new-job', data: 'Второй потоковый ответ' }) });
  });
  await expect(stop).toBeVisible();
  await page.evaluate(() => window.__queueFixture.sockets.at(-1).onmessage({ data: JSON.stringify({
    type: 'agent_reply', job_id: 'new-job', reply: 'Второй потоковый ответ',
  }) }));
  await expect(page.getByText('Второй потоковый ответ', { exact: true })).toHaveCount(1);
  await expect(stop).toHaveCount(0);
  expect(await page.evaluate(() => window.__queueFixture.attempts)).toBe(2);
});

for (const queued of [false, true]) {
  test(`${queued ? 'queued flush' : 'open-socket send'} failure does not replay a request on reconnect`, async ({ page }) => {
    await fixture(page);
    if (!queued) await openLatest(page);
    await page.evaluate(() => { window.__queueFixture.fail = true; });
    await page.getByRole('textbox', { name: 'Сообщение', exact: true }).fill('Синтетический запрос');
    await page.getByRole('button', { name: 'Отправить', exact: true }).click();
    if (queued) await openLatest(page);
    await expect(page.getByText('Сервис временно недоступен.', { exact: true }).first()).toBeVisible();
    await expect(page.getByRole('button', { name: 'Остановить генерацию', exact: true })).toHaveCount(0);
    await page.evaluate(() => {
      const socket = window.__queueFixture.sockets.at(-1);
      socket.readyState = 3;
      socket.onclose({ code: 1006 });
      window.__queueFixture.fail = false;
    });
    await expect.poll(() => page.evaluate(() => window.__queueFixture.sockets.length)).toBe(2);
    await openLatest(page);
    expect(await page.evaluate(() => window.__queueFixture.attempts)).toBe(1);
    expect(await page.evaluate(() => window.__queueFixture.messages.length)).toBe(0);
    await expect(page.locator('body')).not.toContainText('PRIVATE_SEND_FIXTURE');
  });
}
