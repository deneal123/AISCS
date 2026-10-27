const { test, expect } = require('@playwright/test');
const axeCore = require('axe-core');

const THREAD = 'video-progress-thread';

async function installScenario(page, offer = null, requests = [], initialProgress = true) {
  await page.addInitScript(() => {
    localStorage.setItem('telerag:isAuthenticated', JSON.stringify(true));
    localStorage.setItem('auth_token', 'video-test-opaque');
  });
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    let json = {};
    if (path === '/api/profile/me') json = { id: 'video-test-user', email: 'test@example.test', permissions: [] };
    if (path === '/api/chats/') json = { chats: [{ thread_id: THREAD, title: 'Конспект видео' }] };
    if (path === `/api/chats/${THREAD}`) json = { messages: [] };
    if (path.endsWith('/trace')) json = { traces: {} };
    if (path === '/api/chats/models') json = { models: [] };
    if (path === '/api/chats/models/catalog') json = { providers: [], models: [] };
    if (path === '/api/chats/personas') json = [];
    if (path === '/api/chats/transcription/config') json = { enabled: false };
    if (path === '/api/billing/balance') json = { balance: 100000 };
    if (path.includes('parse-url')) json = { title: 'Video page', content: 'Page metadata only' };
    await route.fulfill({ json });
  });
  let socket;
  await page.routeWebSocket('**/api/chats/**/ws*', (ws) => {
    socket = ws;
    ws.onMessage((raw) => {
      const request = JSON.parse(raw);
      if (request.type !== 'message') return;
      requests.push(request);
      if (request.confirm_offer_id) {
        const declined = request.confirmation_decision === 'decline';
        ws.send(JSON.stringify({ type: 'job_created', job_id: 'continued',
          confirmation_status: declined ? 'declined' : 'accepted', confirmation_offer_id: offer.offer_id }));
        ws.send(JSON.stringify({ type: 'agent_reply', job_id: 'continued', reply: declined
          ? 'Продолжаю без платной возможности.' : 'Подтверждённый результат.', metadata: { execution_status: 'completed' } }));
        return;
      }
      ws.send(JSON.stringify({ type: 'job_created', job_id: 'video-test-job', celery_task_id: 'opaque-task' }));
      if (offer) {
        ws.send(JSON.stringify({ type: 'status_update', job_id: 'video-test-job', metadata: {
          kind: 'mode_offer', mode_offer: { ...offer, offered_at: new Date().toISOString(), expires_in_sec: 30 },
        } }));
        ws.send(JSON.stringify({ type: 'agent_reply', job_id: 'video-test-job', reply: 'Waiting', metadata: { awaiting_confirmation: true } }));
        return;
      }
      if (initialProgress) {
        ws.send(JSON.stringify({ type: 'status_update', job_id: 'video-test-job', metadata: {
          kind: 'video_progress', video_progress: { stage: 'download' },
        } }));
      }
    });
  });
  return (frame) => socket.send(JSON.stringify({ job_id: 'video-test-job', ...frame }));
}

test('reading a parked trace does not jump to its expanded bottom', async ({ page }, info) => {
  test.skip(!['chromium', 'mobile-chrome'].includes(info.project.name));
  await page.setViewportSize(info.project.name === 'chromium'
    ? { width: 1440, height: 900 } : { width: 393, height: 851 });
  const errors = [];
  page.on('pageerror', () => errors.push('page_error'));
  await installScenario(page, { mode: 'deep_research', label: 'Исследование', blocking: true,
    offer_kind: 'mode', offer_id: 'scroll-owned-offer', status: 'pending' });
  await page.goto(`/chat/${THREAD}`);
  const input = page.getByPlaceholder('Напишите сообщение...');
  await input.fill(`Проверь материалы\n${'Абзац исходных материалов.\n'.repeat(80)}`);
  await input.press('Enter');
  await expect(page.getByRole('button', { name: 'Использовать', exact: true })).toBeVisible();
  const header = page.getByRole('button', { name: 'Ожидаю ваше решение', exact: true });
  await header.evaluate((button) => {
    let node = button.parentElement;
    while (node && !['auto', 'scroll'].includes(getComputedStyle(node).overflowY)) {
      node = node.parentElement;
    }
    if (!node) throw new Error('chat_scroller_missing');
    node.dataset.acceptanceScroll = 'trace';
  });
  const scroller = page.locator('[data-acceptance-scroll="trace"]');
  if (await header.getAttribute('aria-expanded') === 'true') await header.click();
  await scroller.evaluate((node) => { node.scrollTop = 0; });
  const down = page.getByRole('button', { name: /Прокрутить к последнему сообщению|Новый ответ ниже/ });
  await expect(down).toBeVisible();
  await down.click();
  await expect.poll(() => scroller.evaluate((node) => (
    node.scrollHeight - node.clientHeight - node.scrollTop
  ))).toBeLessThan(3);
  const before = await scroller.evaluate((node) => ({ top: node.scrollTop, height: node.scrollHeight }));
  await header.click();
  await expect(header).toHaveAttribute('aria-expanded', 'true');
  await expect.poll(() => scroller.evaluate((node) => node.scrollHeight)).toBeGreaterThan(before.height);
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await expect.poll(() => scroller.evaluate((node, top) => Math.abs(node.scrollTop - top), before.top)).toBeLessThan(3);
  await expect(page.getByRole('button', { name: 'Продолжить без этого' })).toBeVisible();
  expect(errors).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false);
  await page.addScriptTag({ content: axeCore.source });
  const severe = await page.evaluate(async () => (await window.axe.run(document, {
    runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa'] },
  })).violations.filter((item) => ['critical', 'serious'].includes(item.impact)).map((item) => item.id));
  expect(severe).toEqual([]);
  await page.screenshot({ path: info.outputPath('parked-trace-reading.png') });
});

for (const reasonCode of ['shortcut_smalltalk', 'shortcut_continue']) {
  test(`routing shortcut ${reasonCode} does not claim a free answer or pending consent`, async ({ page }, info) => {
    test.skip(!['chromium', 'mobile-chrome'].includes(info.project.name));
    await page.setViewportSize(info.project.name === 'chromium'
      ? { width: 1440, height: 900 } : { width: 393, height: 851 });
    const pageErrors = [];
    page.on('pageerror', () => pageErrors.push('page_error'));
    const requests = [];
    const send = await installScenario(page, null, requests, false);
    await page.goto(`/chat/${THREAD}`);
    const input = page.getByPlaceholder('Напишите сообщение...');
    await input.fill('привет');
    await input.press('Enter');
    await expect.poll(() => requests.length).toBe(1);
    await expect(page.getByRole('button', { name: 'Ход работы: показать или скрыть этапы' })).toBeVisible();
    send({ type: 'status_update', message: 'Режим выбран', metadata: {
      kind: 'auto_decision', auto: { source: 'shortcut', reason_code: reasonCode },
    } });
    send({ type: 'status_update', metadata: {
      kind: 'tool_availability', tool_availability: {
        offered: ['web_search'], omissions: [{ tool: 'watch_video', reason: 'needs_confirmation' }],
      },
    } });
    const toggle = page.getByRole('button', { name: 'Ход работы: показать или скрыть этапы' });
    if (await toggle.getAttribute('aria-expanded') === 'false') await toggle.click();
    await expect(page.getByText(/Выбор режима — без вызова модели/)).toBeVisible();
    await expect(page.getByRole('status').filter({ hasText: /^Инструменты подготовлены$/ })).toBeVisible();
    await expect(page.getByText(/Доступны только с разрешением:/).first()).toBeVisible();
    await expect(page.getByText('Нужно согласие на инструменты', { exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Использовать', exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Продолжить без этого' })).toHaveCount(0);
    send({ type: 'agent_reply', reply: 'Привет! Чем могу помочь?', metadata: { execution_status: 'completed' } });
    await expect(page.getByText('Привет! Чем могу помочь?', { exact: true })).toBeVisible();
    const completed = page.getByRole('button', { name: 'Ход работы', exact: true });
    if (await completed.getAttribute('aria-expanded') === 'false') await completed.click();
    await expect(page.getByText(/Выбор режима — без вызова модели/)).toBeVisible();
    expect(requests).toHaveLength(1);
    expect(pageErrors).toEqual([]);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
    expect(overflow).toBe(false);
    await page.addScriptTag({ content: axeCore.source });
    const severe = await page.evaluate(async () => (await window.axe.run(document, {
      runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa'] },
    })).violations.filter((item) => ['critical', 'serious'].includes(item.impact)).map((item) => item.id));
    expect(severe).toEqual([]);
    await page.screenshot({ path: info.outputPath(`${reasonCode}-trace.png`), fullPage: true });
  });
}

for (const mode of ['watch_video', 'deep_research', 'image_gen']) {
  test(`${mode}: decision blocks the answer and resumes one anchored trace`, async ({ page }, info) => {
    test.skip(!['chromium', 'tablet', 'mobile-chrome'].includes(info.project.name));
    const requests = [];
    await installScenario(page, { mode, label: 'Платная возможность', blocking: true,
      offer_kind: mode === 'watch_video' ? 'tool' : 'mode', offer_id: 'opaque-owned-offer', status: 'pending' }, requests);
    await page.goto(`/chat/${THREAD}`);
    const prompt = 'Выполни задание с подтверждением';
    await page.getByPlaceholder('Напишите сообщение...').fill(prompt);
    await page.getByPlaceholder('Напишите сообщение...').press('Enter');
    await expect(page.getByRole('button', { name: 'Использовать', exact: true })).toBeVisible();
    const header = page.getByRole('button', { name: 'Ожидаю ваше решение', exact: true });
    await expect(header).toHaveCount(1);
    await header.click();
    await expect(page.getByRole('button', { name: 'Продолжить без этого' })).toBeVisible();
    await expect(page.getByText('Waiting', { exact: true })).toHaveCount(0);
    expect(requests).toHaveLength(1);
    await page.screenshot({ path: info.outputPath(`${mode}-decision.png`), fullPage: true });
    await page.getByRole('button', { name: 'Продолжить без этого' }).click();
    await expect(page.getByText('Продолжаю без платной возможности.', { exact: true })).toBeVisible();
    expect(requests).toHaveLength(2);
    expect(requests[1]).toMatchObject({ text: '', confirm_offer_id: 'opaque-owned-offer', confirmation_decision: 'decline' });
    await expect(page.getByRole('group').filter({ hasText: prompt,
      has: page.getByRole('button', { name: 'Редактировать сообщение' }) })).toHaveCount(1);
    await expect(page.getByRole('button', { name: 'Ход работы', exact: true })).toHaveCount(1);
  });
}

test('consent double click continues once without another user message', async ({ page }, info) => {
  test.skip(!['chromium', 'mobile-chrome'].includes(info.project.name));
  const requests = [];
  await installScenario(page, { mode: 'watch_video', label: 'Просмотр видео', blocking: true,
    offer_kind: 'tool', offer_id: 'owned-consent-offer', status: 'pending' }, requests);
  await page.goto(`/chat/${THREAD}`);
  await page.getByPlaceholder('Напишите сообщение...').fill('Подготовь конспект');
  await page.getByPlaceholder('Напишите сообщение...').press('Enter');
  const approve = page.getByRole('button', { name: 'Использовать', exact: true });
  await expect(approve).toBeVisible();
  await approve.evaluate((button) => { button.click(); button.click(); });
  await expect(page.getByText('Подтверждённый результат.', { exact: true })).toBeVisible();
  expect(requests).toHaveLength(2);
  expect(requests[1]).toMatchObject({ text: '', confirm_offer_id: 'owned-consent-offer' });
  await expect(page.getByText('Подтверждено, запуск начат.', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Ход работы', exact: true })).toHaveCount(1);
});

test('offer expiry never sends consent or manufactures an answer', async ({ page }, info) => {
  test.skip(!['chromium', 'mobile-chrome'].includes(info.project.name));
  await page.clock.install();
  const requests = [];
  await installScenario(page, { mode: 'deep_research', label: 'Исследование', blocking: true,
    offer_kind: 'mode', offer_id: 'owned-expiry-offer', status: 'pending' }, requests);
  await page.goto(`/chat/${THREAD}`);
  await page.getByPlaceholder('Напишите сообщение...').fill('Исследуй вопрос');
  await page.getByPlaceholder('Напишите сообщение...').press('Enter');
  await expect(page.getByRole('button', { name: 'Использовать', exact: true })).toBeVisible();
  await page.clock.fastForward(32_000);
  await expect(page.getByText('Срок подтверждения истёк, запуск не выполнялся.', { exact: true }))
    .toBeVisible();
  expect(requests).toHaveLength(1);
  await expect(page.getByText('Подтверждённый результат.', { exact: true })).toHaveCount(0);
  await expect(page.getByText('Waiting', { exact: true })).toHaveCount(0);
});

test('video stages stay visible, survive silence and complete without a phantom file', async ({ page }, info) => {
  test.skip(!['chromium', 'tablet', 'mobile-chrome'].includes(info.project.name));
  const send = await installScenario(page);
  await page.clock.install();
  await page.goto(`/chat/${THREAD}`);
  await page.getByPlaceholder('Напишите сообщение...').fill('https://www.youtube.com/watch?v=uTR9FdR3Ob0 нужно сделать конспект видео');
  await page.getByPlaceholder('Напишите сообщение...').press('Enter');
  await expect(page.getByText('Загружаю видео').first()).toBeVisible();
  await expect(page.getByText('Ссылки на видео')).toBeVisible();
  const traceToggle = page.getByRole('button', { name: 'Ход работы: показать или скрыть этапы' });
  await traceToggle.click();
  await expect(traceToggle).toHaveAttribute('aria-expanded', 'false');
  await expect(page.getByText('Загружаю видео').first()).toBeVisible();

  await page.clock.runFor(65000);
  await expect(page.getByText(/Нет новых статусов/).first()).toBeVisible();
  send({ type: 'status_update', metadata: { kind: 'video_progress', video_progress: {
    stage: 'transcript', heartbeat: false,
  } } });
  await expect(page.getByText('Получаю субтитры и расшифровку').first()).toBeVisible();
  await expect(page.getByText(/Нет новых статусов/)).toHaveCount(0);
  send({ type: 'status_update', metadata: { kind: 'video_progress', video_progress: {
    stage: 'authoring', current: 2, total: 3,
  } } });
  await expect(page.getByText('Готовлю конспект · часть 2 из 3').first()).toBeVisible();
  const dimensions = await page.evaluate(() => ({ client: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth }));
  expect(dimensions.scroll).toBeLessThanOrEqual(dimensions.client);
  await page.addScriptTag({ content: axeCore.source });
  const severe = await page.evaluate(async () => (await window.axe.run(document, {
    runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa'] },
  })).violations.filter((item) => ['critical', 'serious'].includes(item.impact)).map((item) => item.id));
  expect(severe).toEqual([]);
  await page.screenshot({ path: info.outputPath('video-progress.png'), fullPage: true });
  send({ type: 'agent_reply', reply: 'Конспект сохранён в Рабочем месте. Доставка в Библиотеку пока недоступна.', metadata: { execution_status: 'deferred' } });
  await expect(page.getByText('Готовлю ответ…')).toHaveCount(0);
  await expect(page.getByText(/Доставка в Библиотеку пока недоступна/)).toBeVisible();
  await expect(page.getByText('video-notes.md')).toHaveCount(0);
});
