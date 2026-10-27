const { test, expect } = require('@playwright/test');
const axe = require('axe-core');
const { installVisualViewport } = require('./helpers/visualViewport');
const { trackComposerBounds, attachComposerBounds } = require('./helpers/composerGeometry');
const { watchFirstPickerFrame, firstPickerFrames } = require('./helpers/pickerOpening');
test.use({ serviceWorkers: 'block' });

const THREAD = 'composer-fixture';
const LONG_MODEL = 'openai/very-long-selected-model-name-for-narrow-workbench-layout';
const models = [
  { id: 'GigaChat-2', context_window: 131072, cost_tier: 1, capabilities: ['tools'] },
  { id: 'GigaChat-2-Max', context_window: 131072, cost_tier: 2, capabilities: ['vision', 'tools'] },
  ...Array.from({ length: 305 }, (_, index) => ({ id: `openai/model-${String(index).padStart(3, '0')}`, capabilities: [] })),
  { id: LONG_MODEL, capabilities: [] },
];
const personas = [
  { id: 'engineer', label: 'Инженер', hint: 'Технические объяснения и расчёты' },
  { id: 'analyst', label: 'Аналитик', hint: 'Обработка данных и сопоставление вариантов' },
  { id: 'scientist', label: 'Учёный', hint: 'Научные материалы и источники' },
];

async function fixture(page, state = { unavailable: false }) {
  // Exercise the supported system-font fallback deterministically. CDN/font
  // availability is a separate live concern, not a mocked UI prerequisite.
  await page.route('https://fonts.googleapis.com/**', (route) => route.fulfill({ contentType: 'text/css', body: '' }));
  await page.route('https://fonts.gstatic.com/**', (route) => route.abort());
  if (!state.localFonts) await page.route('**/static/fonts/**/*.woff2', (route) => route.abort());
  await page.addInitScript(() => {
    localStorage.setItem('telerag:isAuthenticated', 'true');
    localStorage.setItem('auth_token', 'composer-fixture-token');
  });
  // Keep mocked UI sessions disconnected from real jobs, even against dev.
  await page.routeWebSocket('**/api/**', state.onSocket || (() => {}));
  await page.route('**/api/**', async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    let json = {};
    if (pathname === '/api/profile/me') json = { id: 'composer-user', email: 'composer@example.test', permissions: [] };
    if (pathname === '/api/chats/') json = { chats: [{ thread_id: THREAD, title: 'Проверка composer' }] };
    if (pathname === `/api/chats/${THREAD}`) json = { messages: state.messages || (state.context ? [{
      id: 'context-fixture', role: 'assistant', content: 'Проверочный ответ',
      metadata: { context: { usable: 100000, used: 0, window: 131072, by_section: {} } },
    }] : []) };
    if (pathname === `/api/chats/${THREAD}/trace`) json = { traces: {} };
    if (pathname === '/api/chats/personas') json = { personas: state.personas || personas };
    if (pathname === '/api/chats/transcription/config') json = state.transcription || { enabled: false };
    if (pathname === '/api/billing/balance') json = { balance: 1000 };
    if (pathname === '/api/chats/providers/status' && state.providerStatus) json = state.providerStatus;
    if (pathname.startsWith('/api/chats/models')) {
      if (state.unavailable || (state.catalogUnavailable && pathname.endsWith('/catalog'))) {
        await route.fulfill({ status: 503, json: { code: 'unavailable' } }); return;
      }
      const catalogModels = state.models || models;
      json = pathname.endsWith('/catalog') ? { models: catalogModels, providers: [] } : { models: catalogModels.map((model) => model.id) };
    }
    if (pathname.endsWith('/work')) json = {
      contract_version: 2,
      workspace: { state: 'absent', revision: '', entries: [], history: [] },
      library: { state: 'ready', items: [], next_cursor: null },
      room: { state: 'absent', leases: [], activity: [], control: { state: 'running' } },
    };
    await route.fulfill({ json });
  });
  await page.goto(`/chat/${THREAD}`);
  // Dev's lazy chunks can load slower while other browser suites are running.
  await expect(page.getByRole('button', { name: 'Личность: Без личности', exact: true })).toBeVisible({ timeout: 15000 });
}

async function noOverflow(page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
}

for (const width of [393, 1440]) {
  for (const reason of ['empty', 'error', 'success']) {
    test(`кольцо контекста обновляет одно уведомление ${reason} ${width}px`, async ({ page }, info) => {
      await page.setViewportSize({ width, height: 851 });
      let socket;
      const requests = [];
      await fixture(page, { context: true, onSocket: connection => {
        socket = connection;
        socket.onMessage(raw => {
          if (JSON.parse(raw).type === 'compact_context') requests.push(JSON.parse(raw));
        });
      } });
      await expect(page.getByRole('status', { name: 'На связи', exact: true })).toBeVisible();
      const ring = page.getByRole('button', { name: /Контекст заполнен/ });
      await ring.focus();
      await ring.press('Enter');
      await expect.poll(() => requests.length).toBe(1);
      await expect(ring).toBeDisabled();
      await expect(page.getByText('Сжимаю контекст…', { exact: true })).toBeVisible();
      // Ответ дольше окна дедупликации обязан заменить всё ещё активный статус.
      await page.waitForTimeout(2200);
      socket.send(JSON.stringify({
        type: 'context_compacted', thread_id: THREAD,
        ok: reason === 'success', reason, summary: 'Проверочное резюме',
      }));
      const title = reason === 'success' ? 'Контекст сжат'
        : reason === 'empty' ? 'Сжимать нечего' : 'Контекст не сжат';
      await expect(page.getByText(title, { exact: true })).toBeVisible();
      await expect(page.getByText('Сжимаю контекст…', { exact: true })).toHaveCount(0);
      await expect(page.getByRole('button', { name: 'Закрыть уведомление', exact: true })).toHaveCount(1);
      await expect(ring).toBeEnabled();
      expect(requests).toHaveLength(1);
      await noOverflow(page);
      await page.screenshot({ path: info.outputPath(`context-${reason}-${width}.png`) });
    });
  }
}

for (const width of [393, 1440]) test(`composer grows only for additional text lines ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 851 });
  await fixture(page);
  const input = page.getByRole('textbox', { name: 'Сообщение', exact: true });
  const container = page.locator('[data-composer-container]:visible');
  const height = () => input.evaluate(element => element.getBoundingClientRect().height);
  const initialHeight = await height();
  const initialGeometry = await container.boundingBox();
  await input.focus();
  expect(await height()).toBe(initialHeight);
  await input.pressSequentially('фа');
  // Дождаться отложенного пересчёта, чтобы не принять старую высоту за результат.
  await input.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await expect.poll(height).toBe(initialHeight);
  expect(await container.boundingBox()).toEqual(initialGeometry);
  await page.screenshot({ path: info.outputPath(`composer-single-line-${width}.png`) });
  await input.press('Shift+Enter');
  await input.pressSequentially('вторая строка');
  await expect.poll(height).toBeGreaterThan(initialHeight);
  await input.fill('длинная строка '.repeat(400));
  await expect.poll(height).toBe(196);
  await expect(input).toHaveCSS('overflow-y', 'auto');
  expect(await input.evaluate(element => element.scrollHeight > element.clientHeight)).toBe(true);
  await input.fill('фа');
  await expect.poll(height).toBe(initialHeight);
  await input.fill('');
  await expect.poll(height).toBe(initialHeight);
  await noOverflow(page);
});

async function edgeState(locator) {
  return locator.evaluate(element => {
    const edge = getComputedStyle(element, '::before');
    return { content: edge.content, animation: edge.animationName, opacity: edge.opacity,
      angle: edge.getPropertyValue('--gold-angle') };
  });
}

for (const width of [393, 1440]) test(`local model is first, free and has a dismissible invitation ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 851 });
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await fixture(page, {
    models: [models[0], { id: 'qwen2.5-1.5b-instruct', provider: 'local', is_free: true,
      context_window: 8192, cost_tier: -1, capabilities: ['tools'] }],
    providerStatus: { state: 'available', ready: 1, total: 1, providers: [
      { id: 'local', label: 'Локальная модель', state: 'ready', primary: false },
    ] },
  });
  await page.getByRole('button', { name: 'Модель: Авто', exact: true }).click();
  const choices = page.getByRole('option');
  const local = choices.first();
  await expect(local).toContainText('Qwen2.5 · 1.5B');
  await expect(local).toContainText('Бесплатно');
  await expect(choices.nth(1)).toContainText('Авто');
  await expect(local).toHaveAttribute('data-choice-local-invitation', 'true');
  expect((await edgeState(local)).animation).toBe('gold-edge-run');
  await page.screenshot({ path: info.outputPath(`local-model-${width}.png`) });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  expect((await edgeState(local)).animation).toBe('none');
  await local.click();
  const selected = page.getByRole('button', { name: 'Модель: Qwen2.5 · 1.5B', exact: true });
  await expect(selected).toBeVisible();
  await selected.click();
  await expect(page.getByRole('option').first()).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByRole('option').first()).not.toHaveAttribute('data-choice-local-invitation');
  await page.keyboard.press('Escape');
  const availability = page.getByTestId('provider-availability');
  await availability.click();
  await expect(page.getByText('Локальная модель', { exact: true })).toBeVisible();
  await expect(page.getByText('Доступен', { exact: true })).toBeVisible();
  await noOverflow(page);
  await page.addScriptTag({ content: axe.source });
  const violations = await page.evaluate(async () => (await window.axe.run()).violations
    .filter(item => ['serious', 'critical'].includes(item.impact)));
  expect(violations).toEqual([]);
});

for (const width of [320, 393, 640]) test(`mobile provider shelf replaces navigation band ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 851 });
  let reads = 0;
  await fixture(page, { context: true, providerStatus: { state: 'available', ready: 1, total: 1,
    providers: [{ id: 'local', label: 'Локальная модель', state: 'ready' }] } });
  page.on('request', request => { if (request.url().includes('/providers/status')) reads += 1; });
  await expect(page.getByRole('group', { name: 'Разделы треда' })).toHaveCount(0);
  const availability = page.getByTestId('provider-availability');
  await expect(availability).toHaveCount(1);
  await expect(page.locator('[data-composer-settings]').getByTestId('provider-availability')).toBeVisible();
  const header = page.locator('header').filter({ has: page.getByRole('button', { name: 'Настройки чата', exact: true }) });
  expect((await header.boundingBox()).height).toBe(56);
  await availability.click();
  const panel = page.getByRole('dialog', { name: 'Доступность ИИ' });
  await expect(panel).toBeVisible();
  await expect(panel.getByText('Локальная модель', { exact: true })).toBeVisible();
  const box = await panel.boundingBox();
  const trigger = await availability.boundingBox();
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(Math.abs(box.x + box.width / 2 - width / 2)).toBeLessThan(1);
  expect(box.y + box.height).toBeLessThanOrEqual(851);
  await expect(panel).toHaveAttribute('aria-modal', 'true');
  await page.screenshot({ path: info.outputPath(`mobile-provider-open-${width}.png`), animations: 'disabled' });
  await page.keyboard.press('Escape');
  await expect(panel).toHaveCount(0);
  await expect(availability).toBeFocused();
  expect(reads).toBe(0);
  await page.getByRole('button', { name: 'Меню аккаунта', exact: true }).click();
  const menu = page.getByTestId('header-user-menu');
  for (const [label, suffix] of [['Чат', ''], ['IDE', '?surface=work'], ['PDF', '?surface=pdf']]) {
    await expect(menu.getByRole('menuitem', { name: label, exact: true })).toHaveAttribute('href', `/chat/${THREAD}${suffix}`);
  }
  await page.keyboard.press('Escape');
  await noOverflow(page);
  await page.screenshot({ path: info.outputPath(`mobile-provider-${width}.png`), animations: 'disabled' });
});

test('mobile provider sheet contains long statuses in a short viewport', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 520 });
  await fixture(page, { providerStatus: { state: 'unavailable', ready: 0, total: 20,
    providers: Array.from({ length: 20 }, (_, index) => ({ id: `provider-${index}`,
      label: `Провайдер с длинным названием ${index + 1}`, state: 'unavailable' })) } });
  await page.getByTestId('provider-availability').click();
  const panel = page.getByRole('dialog', { name: 'Доступность ИИ' });
  await expect(panel).toBeVisible();
  const box = await panel.boundingBox();
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.y + box.height).toBeLessThanOrEqual(520);
  const body = panel.locator('.chakra-modal__body');
  expect(await body.evaluate(element => element.scrollHeight > element.clientHeight)).toBe(true);
  await expect(panel.getByRole('button', { name: 'Закрыть: Доступность ИИ' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('provider-availability')).toBeFocused();
  await noOverflow(page);
});

for (const width of [1440]) test(`next-action navigation cue disappears on activation ${width}px`, async ({ page, browserName }, info) => {
  await page.setViewportSize({ width, height: 851 });
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await fixture(page);
  const peers = page.getByRole('group', { name: 'Разделы треда' });
  for (const label of ['Чат', 'IDE', 'PDF', 'Чат']) {
    const current = peers.getByRole('button', { name: label, exact: true });
    const before = await current.boundingBox();
    await current.click();
    await expect(current).toHaveAttribute('aria-pressed', 'true');
    await page.mouse.move(0, 0);
    await expect(current).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
    await expect(current).not.toHaveAttribute('data-action-hint');
    expect((await edgeState(current)).animation).toBe('none');
    expect(await current.boundingBox()).toEqual(before);
  }
  const current = peers.getByRole('button', { name: 'Чат', exact: true });
  const destination = peers.getByRole('button', { name: 'IDE', exact: true });
  await page.evaluate(() => document.activeElement.blur());
  await destination.hover();
  expect((await edgeState(destination)).animation).toBe('gold-edge-run');
  const initialAngle = (await edgeState(destination)).angle;
  await expect.poll(async () => (await edgeState(destination)).angle).not.toBe(initialAngle);
  await current.focus();
  await page.keyboard.press('Tab');
  await expect(peers.getByRole('button', { name: 'IDE', exact: true })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(peers.getByRole('button', { name: 'IDE', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await page.emulateMedia({ reducedMotion: 'reduce' });
  expect((await edgeState(destination)).animation).toBe('none');
  await expect(destination).not.toHaveCSS('border-color', 'rgba(0, 0, 0, 0)');
  if (browserName === 'chromium') {
    await page.emulateMedia({ forcedColors: 'active' });
    expect(await page.evaluate(() => matchMedia('(forced-colors: active)').matches)).toBe(true);
    await expect(destination).toHaveCSS('border-style', 'solid');
    expect(await destination.evaluate(element => getComputedStyle(element, '::before').display)).toBe('none');
    await page.emulateMedia({ forcedColors: 'none' });
  }
  await peers.getByRole('button', { name: 'Чат', exact: true }).click();
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.getByRole('textbox', { name: 'Сообщение', exact: true }).focus();
  await noOverflow(page);
  await page.screenshot({ path: info.outputPath(`peer-outline-${width}.png`) });
});

for (const width of [393, 1440]) for (const outcome of ['reply', 'error', 'stop']) test(`composer glow stops before ACK and recovers after ${outcome} ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 851 });
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  let socket;
  let requests = 0;
  await fixture(page, { onSocket: connection => {
    socket = connection;
    socket.onMessage(raw => { if (JSON.parse(raw).type === 'message') requests += 1; });
  } });
  await expect(page.getByRole('status', { name: 'На связи', exact: true })).toBeVisible();
  const input = page.getByRole('textbox', { name: 'Сообщение', exact: true });
  const shell = page.locator('[data-composer-input-surface]');
  const peers = page.getByRole('group', { name: 'Разделы треда' });
  await page.getByRole('button', { name: 'Настройки чата', exact: true }).focus();
  expect((await edgeState(shell)).animation).toBe('gold-edge-run');
  await input.fill(`Синтетический запрос ${outcome}`);
  expect((await edgeState(shell)).animation).toBe('none');
  expect((await edgeState(shell)).content).toBe('none');
  await input.blur();
  expect((await edgeState(shell)).animation).toBe('gold-edge-run');
  await page.getByRole('button', { name: 'Отправить', exact: true }).click();
  await expect.poll(() => requests).toBe(1);
  // The server has not acknowledged a job yet: dispatch already stops the hint.
  expect((await edgeState(shell)).animation).toBe('none');
  const stop = page.getByRole('button', { name: 'Остановить генерацию', exact: true });
  await stop.focus();
  expect((await edgeState(shell)).animation).toBe('none');
  if (width >= 768) {
    const destination = peers.getByRole('button', { name: 'PDF', exact: true });
    await destination.hover();
    expect((await edgeState(destination)).animation).toBe('none');
  }
  const job = `glow-fixture-${outcome}`;
  socket.send(JSON.stringify({ type: 'job_created', job_id: job, celery_task_id: job }));
  socket.send(JSON.stringify({ type: 'stream_chunk', job_id: job, data: 'Начат ответ ' }));
  expect((await edgeState(shell)).animation).toBe('none');
  if (outcome === 'stop') await stop.click();
  else socket.send(JSON.stringify(outcome === 'reply'
    ? { type: 'agent_reply', job_id: job, reply: 'Синтетический ответ готов.' }
    : { type: 'error', job_id: job, code: 'auth' }));
  await expect(input).toBeEnabled();
  await input.focus();
  expect((await edgeState(shell)).animation).toBe('none');
  await input.blur();
  expect((await edgeState(shell)).animation).toBe('gold-edge-run');
  await page.emulateMedia({ reducedMotion: 'reduce' });
  expect((await edgeState(shell)).animation).toBe('none');
  expect((await edgeState(shell)).opacity).toBe('1');
  await page.addScriptTag({ content: axe.source });
  const violations = await shell.evaluate(async element => (await window.axe.run(element)).violations
    .filter(item => ['serious', 'critical'].includes(item.impact)));
  expect(violations).toEqual([]);
  await page.screenshot({ path: info.outputPath(`composer-ready-${width}.png`) });
});

for (const width of [393, 1440]) test(`idle invitation pauses behind choice dialogs and preserves geometry ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 851 });
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await fixture(page);
  const input = page.getByRole('textbox', { name: 'Сообщение', exact: true });
  const shell = page.locator('[data-composer-input-surface]');
  await input.blur();
  const initial = await shell.boundingBox();
  expect((await edgeState(shell)).animation).toBe('gold-edge-run');
  await input.focus();
  expect((await edgeState(shell)).animation).toBe('none');
  expect(await shell.boundingBox()).toEqual(initial);
  await page.getByRole('button', { name: 'Режим: Авто', exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'Режим ответа', exact: true })).toBeVisible();
  expect((await edgeState(shell)).animation).toBe('none');
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog', { name: 'Режим ответа', exact: true })).not.toBeVisible();
  await page.getByRole('button', { name: 'Настройки чата', exact: true }).focus();
  expect((await edgeState(shell)).animation).toBe('gold-edge-run');
  await page.getByRole('button', { name: 'Настройки чата', exact: true }).click();
  await expect(page.getByRole('dialog', { name: /^Настройки / })).toBeVisible();
  expect((await edgeState(shell)).animation).toBe('none');
  await page.getByRole('button', { name: 'Закрыть настройки', exact: true }).focus();
  await page.keyboard.press('Escape');
  await expect(page.locator('[aria-modal="true"]')).toHaveCount(0);
  await page.getByRole('button', { name: 'Настройки чата', exact: true }).focus();
  expect((await edgeState(shell)).animation).toBe('gold-edge-run');
  await page.emulateMedia({ reducedMotion: 'reduce' });
  expect((await edgeState(shell)).animation).toBe('none');
  expect((await edgeState(shell)).content).not.toBe('none');
  await input.focus();
  expect((await edgeState(shell)).content).toBe('none');
  expect(await shell.boundingBox()).toEqual(initial);
  await page.screenshot({ path: info.outputPath(`focused-no-hint-${width}.png`) });
});

for (const width of [320, 393, 1440]) test(`composer actions have small visible surfaces and full touch targets ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 851 });
  await fixture(page);
  const input = page.getByRole('textbox', { name: 'Сообщение', exact: true });
  const send = page.getByRole('button', { name: 'Отправить', exact: true });
  await expect(send).toBeDisabled();
  await input.fill('Короткое сообщение');
  await expect(send).toBeEnabled();
  for (const name of ['Прикрепить файл', 'Голосовой ввод', 'Отправить']) {
    const control = page.getByRole('button', { name, exact: true });
    const face = control.locator('[data-composer-action-surface]');
    await expect(control).toHaveCSS('width', '44px');
    await expect(control).toHaveCSS('height', '44px');
    await expect(face).toHaveCSS('width', '32px');
    await expect(face).toHaveCSS('height', '32px');
    await expect(control.locator('svg')).toHaveCSS('width', '16px');
    const beforeHover = await control.boundingBox();
    await control.hover();
    await expect(control).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
    await expect(control).toHaveCSS('box-shadow', 'none');
    expect(await control.boundingBox()).toEqual(beforeHover);
    await control.focus();
    await expect(face).toHaveCSS('outline-style', 'solid');
  }
  const surface = send.locator('[data-composer-submit-surface]');
  await expect(surface).toHaveCSS('width', '32px');
  await expect(surface).toHaveCSS('height', '32px');
  await expect(send).toHaveCSS('width', '44px');
  await expect(send).toHaveCSS('height', '44px');
  await expect(send).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
  await expect(send).toHaveCSS('box-shadow', 'none');
  await expect(surface).toHaveCSS('box-shadow', 'none');
  const before = await send.boundingBox();
  await send.hover();
  expect(await send.boundingBox()).toEqual(before);
  await input.fill('Первая строка\nВторая строка\nТретья строка');
  const voiceControl = page.getByRole('button', { name: 'Голосовой ввод', exact: true });
  const voice = await voiceControl.boundingBox();
  const after = await send.boundingBox();
  expect(Math.abs(after.y + after.height / 2 - voice.y - voice.height / 2)).toBeLessThan(1);
  await expect(surface).toHaveCSS('width', '32px');
  await voiceControl.focus();
  await page.keyboard.press('Tab');
  await expect(send).toBeFocused();
  await expect(surface).toHaveCSS('outline-style', 'solid');
  await input.focus();
  if (width === 393) {
    await page.addScriptTag({ content: axe.source });
    const violations = await page.locator('[data-composer-container]').evaluate(async element =>
      (await window.axe.run(element)).violations.filter(item => ['serious', 'critical'].includes(item.impact)));
    expect(violations).toEqual([]);
  }
  await noOverflow(page);
  await page.mouse.move(0, 0);
  await page.screenshot({ path: info.outputPath(`small-send-surface-${width}.png`) });
});

for (const width of [320, 393, 640, 1440]) test(`onboarding persona density ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 851 });
  await fixture(page, { personas: [...personas,
    { id: 'psychologist', label: 'Психолог', hint: 'Психологический разбор' },
    { id: 'financier', label: 'Финансист', hint: 'Финансовые сценарии' },
    { id: 'tarot', label: 'Таролог', hint: 'Символический разбор' },
  ] });
  await expect(page.getByText(/Выберите специализацию/)).toHaveCount(0);
  const engineer = page.getByRole('button', { name: 'Инженер', exact: true });
  const description = engineer.getByText(personas[0].hint, { exact: true });
  const bounds = await engineer.boundingBox();
  if (width < 768) {
    await expect(description).toBeHidden();
    expect(bounds.width).toBe(56);
    expect(bounds.height).toBe(56);
  } else await expect(description).toBeVisible();
  await engineer.click();
  await expect(engineer).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('button', { name: 'Аналитик', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Учёный', exact: true })).toBeDisabled();
  await noOverflow(page);
  await page.screenshot({ path: info.outputPath(`onboarding-${width}.png`), animations: 'disabled' });
});

for (const width of [393, 640, 1440]) test(`persona hover keeps its hit target stationary ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 1000 });
  await fixture(page);
  const engineer = page.getByRole('button', { name: 'Инженер', exact: true });
  await engineer.scrollIntoViewIfNeeded();
  await page.mouse.move(0, 0);
  const before = await engineer.boundingBox();
  // A stationary pointer at the bottom used to leave the lifted card, repeatedly
  // cancelling/restarting hover. Sample the entire transition, not just its end.
  await page.mouse.move(before.x + before.width / 2, before.y + before.height - 1);
  const samples = await engineer.evaluate(async element => {
    const frames = [];
    for (let i = 0; i < 30; i += 1) {
      await new Promise(resolve => requestAnimationFrame(resolve));
      const { x, y, width, height } = element.getBoundingClientRect();
      frames.push({ x, y, width, height, hovered: element.matches(':hover') });
    }
    return frames;
  });
  for (const sample of samples) {
    for (const key of ['x', 'y', 'width', 'height']) expect(Math.abs(sample[key] - before[key])).toBeLessThan(0.25);
    expect(sample.hovered).toBe(true);
  }
  await page.mouse.down();
  expect(await engineer.boundingBox()).toEqual(before);
  await page.mouse.up();
  await expect(engineer).toHaveAttribute('aria-pressed', 'true');
  await page.mouse.move(0, 0);
  await engineer.focus();
  await engineer.press('Space');
  await expect(engineer).toHaveAttribute('aria-pressed', 'false');
  expect(await engineer.boundingBox()).toEqual(before);
  await noOverflow(page);
  await page.screenshot({ path: info.outputPath(`stationary-persona-${width}.png`) });
});

test('native local Inter renders Russian and Latin chat without external font requests', async ({ page, browserName }, info) => {
  const external = [];
  page.on('request', (request) => {
    if (/fonts\.(googleapis|gstatic)\.com/.test(request.url())) external.push(request.url());
  });
  await fixture(page, { localFonts: true, messages: [{ id: 'font-text', sender: 'agent', content: 'Проверка шрифта — English interface 123' }] });
  await page.evaluate(() => document.fonts.ready);
  const text = page.getByText('Проверка шрифта — English interface 123', { exact: true });
  await expect(text).toBeVisible();
  if (browserName === 'chromium') {
    const cdp = await page.context().newCDPSession(page);
    await cdp.send('DOM.enable');
    await cdp.send('CSS.enable');
    await text.evaluate((element) => element.setAttribute('data-font-proof', 'true'));
    const { root } = await cdp.send('DOM.getDocument');
    const { nodeId } = await cdp.send('DOM.querySelector', { nodeId: root.nodeId, selector: '[data-font-proof]' });
    const { fonts } = await cdp.send('CSS.getPlatformFontsForNode', { nodeId });
    expect(fonts.some((font) => font.isCustomFont && /Inter/.test(font.familyName))).toBe(true);
    await cdp.detach();
  }
  expect(external).toEqual([]);
  await page.screenshot({ path: info.outputPath('native-local-fonts.png') });
});

for (const width of [320, 393]) test(`mobile regression: visible persona choices, aligned peers and safe composer ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 851 });
  await page.addInitScript(() => {
    // Interactive choices must not depend on a reveal observer ever firing.
    window.IntersectionObserver = class { observe() {} unobserve() {} disconnect() {} };
  });
  await fixture(page);
  await page.evaluate(() => document.documentElement.style.setProperty('--app-safe-bottom', '34px'));
  const engineer = page.getByRole('button', { name: 'Инженер', exact: true });
  await expect(engineer).toBeVisible();
  await expect(engineer).toHaveCSS('opacity', '1');
  await engineer.click();
  await expect(engineer).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('group', { name: 'Разделы треда' })).toHaveCount(0);
  await expect(page.locator('[data-composer-settings]').getByTestId('provider-availability')).toBeVisible();
  const shelf = page.locator('[data-composer-container]');
  await expect.poll(() => shelf.evaluate(element => parseFloat(getComputedStyle(element).paddingBottom))).toBeGreaterThanOrEqual(46);
  const field = page.getByRole('textbox', { name: 'Сообщение', exact: true });
  const widthInside = await field.evaluate(element => element.clientWidth - parseFloat(getComputedStyle(element).paddingLeft) - parseFloat(getComputedStyle(element).paddingRight));
  expect(widthInside).toBeGreaterThan(120);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath(`mobile-chat-${width}.png`) });
});

for (const width of [393, 1440]) test(`research model choice persists after reload ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 851 });
  // Data/focus tests do not time decorative animation. Its normal-motion
  // behavior has separate coverage above; include the OS reduced-motion path.
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await fixture(page);
  await page.getByRole('button', { name: 'Настройки чата', exact: true }).click();
  const dialog = page.getByRole('dialog');
  const input = dialog.getByRole('combobox', { name: 'Модель ресёрча', exact: true });
  await expect(dialog).toHaveCSS('transform', 'none');
  await input.scrollIntoViewIfNeeded();
  await input.press('ArrowDown');
  await expect(page.getByRole('option')).toHaveCount(3);
  const option = page.getByRole('option', { name: 'GigaChat-2-Max', exact: true });
  expect(await option.evaluate(element => Boolean(element.closest('[role="dialog"]')))).toBe(true);
  await option.click();
  await expect(dialog.getByText('GigaChat-2-Max', { exact: true })).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: 'Настройки чата', exact: true }).click();
  await expect(dialog.getByText('GigaChat-2-Max', { exact: true })).toBeVisible();
});

for (const width of [393, 1440]) test(`saved research model reaches the research request ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 851 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.addInitScript(() => {
    localStorage.setItem('gpthub.chat.ui.settings', JSON.stringify({ ldrModel: 'GigaChat-2-Max' }));
  });
  const requests = [];
  await fixture(page, { onSocket: socket => socket.onMessage(raw => {
    const request = JSON.parse(raw);
    if (request.type === 'message') requests.push(request);
  }) });
  await page.getByRole('button', { name: 'Режим: Авто', exact: true }).click();
  await page.getByRole('option', { name: /^Deep Research/ }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('textbox', { name: 'Сообщение', exact: true }).fill('Синтетическая проверка выбора модели');
  await expect(page.getByRole('textbox', { name: 'Сообщение', exact: true })).toHaveValue('Синтетическая проверка выбора модели');
  await page.getByRole('button', { name: 'Отправить', exact: true }).click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0]).toMatchObject({ ldr_model: 'GigaChat-2-Max', route_override: 'deep_research' });
  expect(requests[0].model).not.toBe('GigaChat-2-Max');
});

for (const width of [393, 1440]) test(`research catalog failure offers recovery instead of a default-only list ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 851 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const state = { catalogUnavailable: true };
  await fixture(page, state);
  await page.getByRole('button', { name: 'Настройки чата', exact: true }).click();
  const dialog = page.getByRole('dialog');
  const retry = dialog.getByRole('button', { name: 'Повторить загрузку моделей', exact: true });
  await retry.scrollIntoViewIfNeeded();
  await expect(dialog.getByText(/Не удалось загрузить сведения о моделях/)).toBeVisible();
  state.catalogUnavailable = false;
  await retry.click();
  await expect(retry).toHaveCount(0);
  const input = dialog.getByRole('combobox', { name: 'Модель ресёрча', exact: true });
  await input.press('ArrowDown');
  await expect(page.getByRole('option')).toHaveCount(3);
  const bounds = await dialog.boundingBox();
  const option = await page.getByRole('option', { name: 'GigaChat-2-Max', exact: true }).boundingBox();
  expect(option.x).toBeGreaterThanOrEqual(bounds.x);
  expect(option.x + option.width).toBeLessThanOrEqual(bounds.x + bounds.width);
  if (width === 393) {
    await page.addScriptTag({ content: axe.source });
    const violations = await dialog.getByRole('group', { name: 'Настройка модели ресёрча' })
      .evaluate(async element => (await window.axe.run(element)).violations
        .filter(item => ['serious', 'critical'].includes(item.impact)));
    expect(violations).toEqual([]);
  }
  await page.getByRole('option', { name: 'GigaChat-2', exact: true }).click();
  await expect(dialog.getByText('GigaChat-2', { exact: true })).toBeVisible();
});

test('mobile regression: Settings voice controls remain scrollable above a panned keyboard', async ({ page }, info) => {
  await page.setViewportSize({ width: 393, height: 851 });
  await installVisualViewport(page);
  await fixture(page, { transcription: { enabled: true, local_enabled: true, default_model: 'base', models: ['base', 'small'] } });
  await page.getByRole('button', { name: 'Настройки чата', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('button', { name: 'Локально', exact: true }).click();
  await page.evaluate(() => window.setTestVisualViewport(360, 40));
  const whisper = dialog.getByRole('combobox', { name: 'Модель whisper', exact: true });
  await whisper.scrollIntoViewIfNeeded();
  await whisper.focus();
  const whisperBounds = await whisper.boundingBox();
  const headerBounds = await dialog.locator('.chakra-modal__header').boundingBox();
  expect(whisperBounds.y).toBeGreaterThanOrEqual(headerBounds.y + headerBounds.height);
  expect(whisperBounds.y + whisperBounds.height).toBeLessThanOrEqual(400);
  await whisper.press('ArrowDown');
  await page.getByRole('option', { name: 'small', exact: true }).click();
  await expect(dialog.getByText('small', { exact: true })).toBeVisible();
  const note = dialog.getByText('Настройки сохраняются локально в этом браузере', { exact: true });
  await note.scrollIntoViewIfNeeded();
  await expect(note).toBeVisible();
  const bounds = await note.boundingBox();
  expect(bounds.y + bounds.height).toBeLessThanOrEqual(400);
  const body = dialog.locator('.chakra-modal__body');
  expect(await body.evaluate(element => element.scrollHeight > element.clientHeight && element.scrollTop > 0)).toBe(true);
  await page.screenshot({ path: info.outputPath('mobile-settings-keyboard.png') });
  await dialog.getByRole('button', { name: 'Закрыть настройки', exact: true }).click();
});

test('Markdown headings keep first/later spacing without Emotion selector warnings', async ({ page }) => {
  const warnings = [];
  page.on('console', (message) => { if (message.text().includes('pseudo class ":first-child"')) warnings.push(message.text()); });
  await fixture(page, { messages: [{ id: 'headings-fixture', sender: 'agent',
    content: '# Начальный заголовок\n\nВводный абзац\n\n## Следующий раздел' }] });
  const first = page.getByRole('heading', { name: 'Начальный заголовок', exact: true });
  const later = page.getByRole('heading', { name: 'Следующий раздел', exact: true });
  await expect(first).toHaveCSS('margin-top', '0px');
  expect(await later.evaluate((element) => parseFloat(getComputedStyle(element).marginTop))).toBeGreaterThan(0);
  expect(warnings).toEqual([]);
});

test('activating context does not leave its delayed hint over the mobile sidebar', async ({ page }) => {
  await page.setViewportSize({ width: 393, height: 851 });
  await fixture(page, { context: true });
  const context = page.getByRole('button', { name: /Контекст заполнен на 0%/ });
  await context.focus();
  await context.click();
  await page.getByRole('button', { name: 'Меню', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Закрыть меню', exact: true })).toBeVisible();
  // Observe past the real 200ms Tooltip enter delay; an immediate negative
  // assertion would miss the delayed-open race being tested.
  await page.waitForTimeout(350);
  await expect(page.getByRole('tooltip')).toBeHidden();
});

test('mobile messages keep safe reading gutters for prose, lists, tables and code', async ({ page }, info) => {
  const paragraph = 'Ответ с безопасным отступом: текст не должен прижиматься к краю экрана.';
  const columns = Array.from({ length: 8 }, (_, index) => `Колонка ${index + 1}`);
  await page.setViewportSize({ width: 393, height: 851 });
  await fixture(page, { messages: [
    { id: 'gutter-user', sender: 'user', content: 'Проверить поля сообщения' },
    { id: 'gutter-assistant', sender: 'agent', content: [paragraph,
      '- Первый пункт\n- Второй пункт',
      `| ${columns.join(' | ')} |\n| ${columns.map(() => '---').join(' | ')} |\n| ${columns.join(' | ')} |`,
      '```\n' + 'long_source_line_'.repeat(25) + '\n```',
    ].join('\n\n') },
  ] });
  for (const width of [393, 320]) {
    await page.setViewportSize({ width, height: 851 });
    const scroller = page.locator('[data-chat-scroll]');
    const padding = await scroller.evaluate((element) => {
      const style = getComputedStyle(element);
      return { left: parseFloat(style.paddingLeft), right: parseFloat(style.paddingRight) };
    });
    expect(padding.left).toBeGreaterThanOrEqual(16);
    expect(padding.right).toBeGreaterThanOrEqual(16);
    const text = page.getByText(paragraph, { exact: true });
    await expect(text).toBeVisible();
    for (const item of [text, page.getByText('Проверить поля сообщения', { exact: true }), scroller.locator('table'), scroller.locator('pre')]) {
      const bounds = await item.boundingBox();
      expect(bounds.x).toBeGreaterThanOrEqual(16);
      expect(bounds.x + bounds.width).toBeLessThanOrEqual(width - 16);
    }
    await noOverflow(page);
    await page.screenshot({ path: info.outputPath(`chat-reading-gutters-${width}.png`) });
  }
});

test('mobile text fields stay readable on focus without requesting automatic magnification', async ({ page }) => {
  await page.setViewportSize({ width: 393, height: 851 });
  await fixture(page);
  const input = page.getByRole('textbox', { name: 'Сообщение', exact: true });
  expect(await input.evaluate((element) => parseFloat(getComputedStyle(element).fontSize))).toBeGreaterThanOrEqual(16);
  const initialScale = await page.evaluate(() => window.visualViewport?.scale || 1);
  await input.fill('Сохранить текст при фокусе');
  await expect(input).toBeFocused();
  expect(await page.evaluate(() => window.visualViewport?.scale || 1)).toBeCloseTo(initialScale, 2);
  await page.getByRole('button', { name: 'Модель: Авто', exact: true }).click();
  const search = page.getByRole('combobox', { name: 'Поиск модели' });
  expect(await search.evaluate((element) => parseFloat(getComputedStyle(element).fontSize))).toBeGreaterThanOrEqual(16);
  await search.fill('GigaChat');
  await expect(search).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(input).toHaveValue('Сохранить текст при фокусе');
  await noOverflow(page);
  const viewport = await page.locator('meta[name="viewport"]').getAttribute('content');
  expect(viewport).not.toMatch(/user-scalable\s*=\s*(no|0)|maximum-scale\s*=\s*1(?:\D|$)/i);
});

test('context ring shares the model control vertical center at desktop and mobile widths', async ({ page }, info) => {
  await fixture(page, { context: true });
  for (const width of [1440, 900, 768, 393, 320]) {
    await page.setViewportSize({ width, height: 900 });
    const model = page.getByRole('button', { name: 'Модель: Авто', exact: true });
    const gauge = page.getByRole('button', { name: /Контекст заполнен на 0%/ });
    await expect.poll(async () => {
      const box = await model.boundingBox();
      const ring = await gauge.locator('svg').boundingBox();
      return box && ring ? Math.abs(ring.y + ring.height / 2 - box.y - box.height / 2) : Infinity;
    }, { message: `vertical center at ${width}px` }).toBeLessThan(0.75);
    await expect.poll(async () => {
      const holder = await page.locator('[data-composer-context]').boundingBox();
      const target = await gauge.boundingBox();
      return holder && target ? Math.abs(holder.height - target.height) : Infinity;
    }, { message: `no inline baseline gap at ${width}px` }).toBeLessThan(0.1);
    await page.screenshot({ path: info.outputPath(`context-alignment-${width}.png`) });
  }
});

test('mobile choices and context share one compact icon row at narrow widths', async ({ page }, info) => {
  await fixture(page, { context: true });
  for (const width of [393, 320]) {
    await page.setViewportSize({ width, height: 851 });
    const input = page.getByRole('textbox', { name: 'Сообщение', exact: true });
    await expect(input).toHaveAttribute('placeholder', 'Сообщение…');
    const placeholderFits = await input.evaluate((element) => {
      const style = getComputedStyle(element);
      const canvas = document.createElement('canvas');
      const context = canvas.getContext('2d');
      context.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
      const usableWidth = element.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
      return context.measureText(element.placeholder).width <= usableWidth;
    });
    expect(placeholderFits).toBe(true);
    const gauge = page.getByRole('button', { name: /Контекст заполнен на 0%/ });
    const bounds = await gauge.boundingBox();
    expect(bounds.width).toBe(44);
    expect(bounds.height).toBe(44);
    const ring = await gauge.locator('svg').boundingBox();
    const number = await gauge.locator('p').boundingBox();
    expect(ring.width).toBe(30);
    expect(ring.height).toBe(30);
    expect(Math.abs(ring.x + ring.width / 2 - number.x - number.width / 2)).toBeLessThan(1);
    expect(Math.abs(ring.y + ring.height / 2 - number.y - number.height / 2)).toBeLessThan(1);
    const model = await page.getByRole('button', { name: 'Модель: Авто', exact: true }).boundingBox();
    expect(model.width).toBe(44);
    expect(bounds.x).toBeGreaterThan(model.x + model.width);
    const mode = await page.getByRole('button', { name: 'Режим: Авто', exact: true }).boundingBox();
    const persona = await page.getByRole('button', { name: 'Личность: Без личности', exact: true }).boundingBox();
    expect(persona.x - mode.x - mode.width).toBeCloseTo(6, 0);
    expect(model.x - persona.x - persona.width).toBeCloseTo(6, 0);
    expect(bounds.x - model.x - model.width).toBeCloseTo(6, 0);
    const row = await page.locator('[data-composer-settings]').boundingBox();
    const availability = await page.getByTestId('provider-availability').boundingBox();
    expect(availability.x - bounds.x - bounds.width).toBeCloseTo(6, 0);
    expect(availability.width).toBe(44);
    expect(availability.height).toBe(44);
    expect(Math.abs((mode.x + availability.x + availability.width) / 2 - row.x - row.width / 2)).toBeLessThan(1);
    for (const name of ['Режим: Авто', 'Личность: Без личности', 'Модель: Авто']) {
      const trigger = page.getByRole('button', { name, exact: true });
      await expect(trigger).toHaveText('');
      await expect(trigger.locator('svg')).toHaveCount(1);
      const target = await trigger.boundingBox();
      expect(target.width).toBe(44);
      expect(target.height).toBe(44);
      expect(Math.abs(target.y - bounds.y)).toBeLessThan(1);
      const icon = await trigger.locator('svg').boundingBox();
      expect(icon.width).toBe(16);
      expect(icon.height).toBe(16);
      const visible = await trigger.locator('[data-choice-glyph]').boundingBox();
      expect(visible.width).toBe(ring.width);
      expect(visible.height).toBe(ring.height);
      expect(Math.abs(visible.y - ring.y)).toBeLessThan(1);
      expect(Math.abs(icon.x + icon.width / 2 - target.x - target.width / 2)).toBeLessThan(1);
      expect(Math.abs(icon.y + icon.height / 2 - target.y - target.height / 2)).toBeLessThan(1);
    }
    expect((await page.locator('[data-composer-settings]').boundingBox()).height).toBe(44);
    await noOverflow(page);
    await page.screenshot({ path: info.outputPath(`composer-context-${width}.png`) });
  }
});

test('composer retains text across choices, surface changes and breakpoints', async ({ page }, info) => {
  await fixture(page);
  const text = page.getByRole('textbox', { name: 'Сообщение', exact: true });
  await text.fill('Не потерять этот текст');
  await page.getByRole('button', { name: 'Модель: Авто', exact: true }).click();
  const search = page.getByRole('combobox', { name: 'Поиск модели', exact: true });
  await search.fill('GigaChat-2-Max');
  await page.setViewportSize({ width: 393, height: 851 });
  await expect(page.getByRole('dialog', { name: 'Модель ответа' })).toBeVisible();
  await expect(search).toHaveValue('GigaChat-2-Max');
  await page.getByRole('option', { name: /^GigaChat-2-Max/ }).click();
  await expect(page.getByRole('button', { name: 'Модель: GigaChat-2-Max', exact: true })).toBeVisible();
  await expect(text).toHaveValue('Не потерять этот текст');
  await page.getByRole('button', { name: 'IDE', exact: true }).click();
  await page.getByRole('button', { name: 'Чат', exact: true }).click();
  await expect(text).toHaveValue('Не потерять этот текст');
  await noOverflow(page);
  await page.screenshot({ path: info.outputPath('composer-mobile.png') });
});

for (const width of [320, 393, 640]) test(`mobile persona icons preserve ordered selection and touch descriptions ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 700 });
  await fixture(page, { personas: [
    ...personas,
    { id: 'psychologist', label: 'Психолог', hint: 'Чувства и потребности' },
    { id: 'financier', label: 'Финансист', hint: 'Сценарии и риски' },
    { id: 'tarot', label: 'Таролог', hint: 'Символы и архетипы' },
  ] });
  const draft = page.getByRole('textbox', { name: 'Сообщение', exact: true });
  await draft.fill('Не потерять черновик при выборе личности');
  await page.getByRole('button', { name: 'Личность: Без личности', exact: true }).click();
  const panel = page.getByRole('dialog').filter({ has: page.getByRole('combobox', { name: 'Выбор личностей' }) });
  await expect(panel).toHaveCSS('width', '280px');
  await expect(panel.getByRole('listbox')).toHaveAttribute('aria-multiselectable', 'true');
  const engineer = panel.getByRole('option', { name: 'Инженер', exact: true });
  const analyst = panel.getByRole('option', { name: 'Аналитик', exact: true });
  const scientist = panel.getByRole('option', { name: 'Учёный', exact: true });
  for (const option of await panel.getByRole('option').all()) {
    await expect(option.locator('svg[data-persona-icon]')).toBeVisible();
  }
  const boxes = await panel.getByRole('option').evaluateAll(elements => elements.map(element => {
    const { width, height, y } = element.getBoundingClientRect();
    return { width, height, y };
  }));
  for (const box of boxes) {
    expect(Math.round(box.width)).toBe(44);
    expect(box.height).toBeGreaterThanOrEqual(44);
  }
  expect(new Set(boxes.map(box => Math.round(box.y))).size).toBe(2);
  await analyst.click();
  await engineer.click();
  await expect(analyst.locator('[data-persona-order]')).toHaveText('1');
  await expect(engineer.locator('[data-persona-order]')).toHaveText('2');
  await expect(scientist).toHaveAttribute('aria-disabled', 'true');
  // Exercise the app guard, not Playwright's refusal to click aria-disabled.
  await scientist.click({ force: true });
  await expect(scientist).toHaveAttribute('aria-selected', 'false');
  await analyst.click();
  await expect(engineer.locator('[data-persona-order]')).toHaveText('1');
  await expect(scientist).toHaveAttribute('aria-disabled', 'false');
  await panel.getByRole('button', { name: 'Показать описания личностей' }).click();
  await expect(panel.getByRole('option', { name: /^Инженер/ }).getByText('Технические объяснения и расчёты', { exact: true })).toBeVisible();
  await panel.getByRole('button', { name: 'Скрыть описания личностей' }).click();
  await expect(engineer.locator('svg[data-persona-icon]')).toBeVisible();
  await page.mouse.move(0, 0);
  await page.screenshot({ path: info.outputPath(`persona-icons-${width}.png`) });
  await page.addScriptTag({ content: axe.source });
  const violations = await panel.evaluate(async element => (await window.axe.run(element)).violations
    .filter(item => ['serious', 'critical'].includes(item.impact)));
  expect(violations).toEqual([]);
  await panel.getByRole('button', { name: 'Без личности', exact: true }).click();
  await expect(panel.getByText('Выбрано 0 из 2', { exact: true })).toBeVisible();
  const input = panel.getByRole('combobox', { name: 'Выбор личностей' });
  await input.focus();
  await input.press('ArrowDown');
  const activeId = await input.getAttribute('aria-activedescendant');
  const active = page.locator(`[id="${activeId}"]`);
  await expect(active).toHaveCSS('outline-style', 'solid');
  await expect(page.getByRole('tooltip')).toContainText(await active.getAttribute('aria-label'));
  await input.press('Enter');
  await expect(panel.getByText('Выбрано 1 из 2', { exact: true })).toBeVisible();
  await panel.getByRole('button', { name: 'Без личности', exact: true }).click();
  await panel.getByRole('button', { name: 'Готово', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Личность: Без личности', exact: true })).toBeFocused();
  await expect(draft).toHaveValue('Не потерять черновик при выборе личности');
  await noOverflow(page);
});

for (const width of [320, 393, 640]) test(`mobile mode palette uses content width without an empty action shelf ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 700 });
  await fixture(page);
  await page.evaluate(() => document.documentElement.style.setProperty('--app-safe-bottom', '34px'));
  const trigger = page.getByRole('button', { name: 'Режим: Авто', exact: true });
  await trigger.click();
  const palette = page.getByRole('dialog').filter({ has: page.getByRole('combobox', { name: 'Выбор режима' }) });
  await expect(palette).toHaveCSS('width', '280px');
  await expect(palette.getByRole('button', { name: 'Закрыть', exact: true })).toHaveCount(0);
  const bounds = await palette.boundingBox();
  expect(bounds.height).toBeLessThanOrEqual(220);
  expect(Math.abs(bounds.x - (width - bounds.width) / 2)).toBeLessThanOrEqual(1);
  for (const option of await palette.getByRole('option').all()) {
    const box = await option.boundingBox();
    expect(Math.round(box.width)).toBe(44);
    expect(box.height).toBeGreaterThanOrEqual(44);
  }
  const strategies = palette.getByRole('group', { name: 'Стратегии ответа', exact: true });
  const multi = strategies.getByRole('button', { name: 'Мульти-интент', exact: true });
  const planning = strategies.getByRole('button', { name: 'Планирование', exact: true });
  const multiBox = await multi.boundingBox();
  const planningBox = await planning.boundingBox();
  expect(planningBox.x - multiBox.x - multiBox.width).toBeLessThanOrEqual(8);
  await expect.poll(async () => {
    const box = await planning.boundingBox();
    return box.y + box.height;
  }).toBeLessThanOrEqual(700 - 34);
  await planning.click();
  await expect(planning).toHaveAttribute('aria-pressed', 'true');
  await palette.getByRole('button', { name: 'Показать описания режимов' }).click();
  const expanded = await palette.evaluate(element => {
    const style = getComputedStyle(element);
    return { width: style.width, maxWidth: style.maxWidth, minWidth: style.minWidth, viewport: innerWidth };
  });
  expect(expanded.width, JSON.stringify(expanded)).toBe(`${Math.min(320, width - 24)}px`);
  await palette.getByRole('button', { name: 'Скрыть описания режимов' }).click();
  await expect(palette).toHaveCSS('width', '280px');
  await page.mouse.move(0, 0);
  await page.screenshot({ path: info.outputPath(`content-sized-mode-${width}.png`) });
  await palette.getByRole('button', { name: 'Закрыть: Режим ответа', exact: true }).click();
  await expect(trigger).toBeFocused();
  await noOverflow(page);
});

test('mode palette does not retain a previous focus ring after pointer selection', async ({ page, isMobile }, info) => {
  await page.setViewportSize({ width: 393, height: 851 });
  await fixture(page);
  await page.getByRole('button', { name: 'Режим: Авто', exact: true }).click();
  const imageChoice = page.getByRole('option', { name: 'Изображение', exact: true });
  if (isMobile) await imageChoice.tap();
  else await imageChoice.click();
  const trigger = page.getByRole('button', { name: 'Режим: Изображение', exact: true });
  await trigger.click();
  const palette = page.getByRole('dialog').filter({ has: page.getByRole('combobox', { name: 'Выбор режима' }) });
  const image = palette.getByRole('option', { name: 'Изображение', exact: true });
  await expect(image).toHaveAttribute('aria-selected', 'true');
  for (const option of await palette.getByRole('option').all()) await expect(option).toHaveCSS('outline-style', 'none');
  const auto = palette.getByRole('option', { name: 'Авто', exact: true });
  // react-select can retain an internal active option. It is not another selection.
  await auto.hover();
  await page.mouse.move(0, 0);
  for (const option of await palette.getByRole('option').all()) await expect(option).toHaveCSS('outline-style', 'none');
  await expect(auto).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
  const input = palette.getByRole('combobox', { name: 'Выбор режима' });
  await palette.getByRole('button', { name: 'Закрыть: Режим ответа', exact: true }).focus();
  await page.keyboard.press('Tab');
  await expect(input).toBeFocused();
  const tabActiveId = await input.getAttribute('aria-activedescendant');
  await expect(page.locator(`[id="${tabActiveId}"]`)).toHaveCSS('outline-style', 'solid');
  await input.press('ArrowDown');
  const activeId = await input.getAttribute('aria-activedescendant');
  expect(activeId).toBeTruthy();
  const active = page.locator(`[id="${activeId}"]`);
  await expect(active).toHaveCSS('outline-style', 'solid');
  await expect(image).toHaveAttribute('aria-selected', 'true');
  await auto.hover();
  await expect(active).toHaveCSS('outline-style', 'none');
  await page.mouse.move(0, 0);
  await page.screenshot({ path: info.outputPath('mode-pointer-keyboard-focus.png') });
});

test('compact mode palette follows the composer width with focused help and touch descriptions', async ({ page }, info) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await fixture(page);
  const input = page.getByRole('textbox', { name: 'Сообщение', exact: true });
  await input.fill('Черновик сохраняется при выборе режима');
  // Exercise the same container-width owner used by a resizable IDE/PDF rail.
  await page.locator('[data-composer-container]').evaluate(element => {
    element.style.width = '500px'; element.style.maxWidth = '100%';
  });
  const trigger = page.getByRole('button', { name: 'Режим: Авто', exact: true });
  await expect(trigger).toHaveText('');
  await trigger.click();
  const picker = page.getByRole('dialog').filter({ has: page.getByRole('combobox', { name: 'Выбор режима' }) });
  await expect(picker.getByText('Быстрый выбор')).toHaveCount(0);
  await expect(picker).toHaveCSS('width', '88px');
  await expect(picker).toHaveCSS('background-color', 'rgb(10, 12, 18)');
  expect((await picker.boundingBox()).height).toBeLessThan(450);
  const rows = await picker.getByRole('option').all();
  const rowBounds = await Promise.all(rows.map(row => row.boundingBox()));
  for (let index = 0; index < rowBounds.length; index += 1) {
    expect(Math.round(rowBounds[index].width)).toBe(44);
    expect(Math.round(rowBounds[index].x)).toBe(Math.round(rowBounds[0].x));
    if (index) expect(rowBounds[index].y).toBeGreaterThanOrEqual(rowBounds[index - 1].y + 44);
  }
  const web = picker.getByRole('option', { name: 'Веб-поиск', exact: true });
  await expect(web).toHaveCSS('min-height', '44px');
  await expect.poll(async () => Math.round((await web.boundingBox()).height)).toBeGreaterThanOrEqual(44);
  await expect(web).not.toContainText('Актуальные сведения');
  await web.hover();
  await expect(page.getByRole('tooltip')).toContainText('С надбавкой за поиск');
  await page.screenshot({ path: info.outputPath('compact-mode-desktop.png'), animations: 'disabled' });
  const modes = picker.getByRole('combobox', { name: 'Выбор режима' });
  await modes.focus();
  await modes.press('ArrowDown');
  await expect(page.getByRole('tooltip').filter({ hasText: 'Deep Research' })).toBeVisible();
  await modes.press('Escape');
  await expect(trigger).toBeFocused();
  await trigger.press('Enter');
  await expect(picker.getByRole('option', { name: 'Веб-поиск', exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(trigger).toBeFocused();
  await page.setViewportSize({ width: 393, height: 700 });
  await trigger.click();
  await expect(picker.getByRole('option', { name: 'Авто', exact: true })).toBeVisible();
  await picker.getByRole('button', { name: 'Показать описания режимов' }).click();
  await expect(picker.getByRole('option', { name: /Веб-поиск/ })).toContainText('С надбавкой за поиск');
  await picker.getByRole('button', { name: 'Скрыть описания режимов' }).click();
  await page.screenshot({ path: info.outputPath('compact-mode-mobile.png'), animations: 'disabled' });
  await page.addScriptTag({ content: axe.source });
  const failures = await picker.evaluate(async element => (await window.axe.run(element)).violations
    .filter(item => ['serious', 'critical'].includes(item.impact)));
  expect(failures).toEqual([]);
  await picker.getByRole('option', { name: 'Веб-поиск', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Режим: Веб-поиск', exact: true })).toBeFocused();
  await expect(input).toHaveValue('Черновик сохраняется при выборе режима');
  await noOverflow(page);
});

for (const name of ['Режим: Авто', 'Личность: Без личности', 'Модель: Авто']) {
  test(`cold picker keeps its position from the first frame: ${name}`, async ({ page }, info) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    await fixture(page);
    const trigger = page.getByRole('button', { name, exact: true });
    await watchFirstPickerFrame(trigger);
    await trigger.click();
    const frames = await firstPickerFrames(page);
    await info.attach('first-picker-frames', { body: JSON.stringify(frames), contentType: 'application/json' });
    for (const frame of frames) {
      for (const dimension of ['x', 'y', 'width', 'height']) {
        expect(Math.abs(frame[dimension] - frames.at(-1)[dimension]), dimension).toBeLessThanOrEqual(1);
      }
    }
    await page.keyboard.press('Escape');
    await expect(trigger).toBeFocused();
  });
}

test('all three pickers have safe geometry and keyboard focus restoration', async ({ page }, info) => {
  const viewports = {
    chromium: { width: 1440, height: 900 },
    'mobile-chrome': { width: 393, height: 851 },
    tablet: { width: 900, height: 900 },
  };
  if (viewports[info.project.name]) await page.setViewportSize(viewports[info.project.name]);
  await fixture(page);
  const triggers = ['Режим: Авто', 'Личность: Без личности', 'Модель: Авто'];
  const inputs = ['Выбор режима', 'Выбор личностей', 'Поиск модели'];
  const narrow = page.viewportSize().width < 768;
  for (let index = 0; index < triggers.length; index += 1) {
    const trigger = page.getByRole('button', { name: triggers[index], exact: true });
    const box = await trigger.boundingBox();
    expect(box.height).toBeGreaterThanOrEqual(narrow ? 44 : 34);
    await trigger.click();
    const input = page.getByRole('combobox', { name: inputs[index], exact: true });
    await expect(input).toBeVisible();
    const dialog = page.getByRole('dialog').filter({ has: input });
    // Bound the settled surface, not a frame of the library's entry animation.
    await expect.poll(async () => {
      const bounds = await dialog.boundingBox();
      return bounds.y + bounds.height;
    }).toBeLessThanOrEqual(page.viewportSize().height + 1);
    const panel = await dialog.boundingBox();
    expect(panel.x).toBeGreaterThanOrEqual(0);
    expect(panel.x + panel.width).toBeLessThanOrEqual(page.viewportSize().width + 1);
    expect(panel.y).toBeGreaterThanOrEqual(0);
    expect(panel.y + panel.height).toBeLessThanOrEqual(page.viewportSize().height + 1);
    if (!narrow && index < 2) expect(panel.x).toBeGreaterThanOrEqual(box.x - 1);
    await input.focus();
    await page.screenshot({ path: info.outputPath(`composer-picker-${index}.png`) });
    await page.keyboard.press('Escape');
    await expect(trigger).toBeFocused();
  }
  await noOverflow(page);
  await page.screenshot({ path: info.outputPath('composer-closed.png') });
});

test.describe('compact composer panels', () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    if (process.env.E2E_COMPOSER_GEOMETRY_DIAGNOSTICS === '1') await trackComposerBounds(page);
    await fixture(page);
    await page.locator('[data-composer-container]').evaluate(element => { element.style.width = '500px'; });
    // Проверяем завершение переключения ResizeObserver в компактный вариант.
    await expect(page.getByRole('textbox', { name: 'Сообщение', exact: true })).toHaveAttribute('placeholder', 'Сообщение…');
  });

  test.afterEach(async ({ page }, info) => {
    if (process.env.E2E_COMPOSER_GEOMETRY_DIAGNOSTICS === '1') await attachComposerBounds(page, info);
  });

  test('persona surface omits repeated prose and expands descriptions explicitly', async ({ page }, info) => {
    await page.getByRole('button', { name: 'Личность: Без личности', exact: true }).click();
    const panel = page.getByRole('dialog').filter({ has: page.getByRole('combobox', { name: 'Выбор личностей' }) });
    await expect(panel).toHaveCSS('width', '240px');
    await expect(panel.getByText(personas[0].hint, { exact: true })).toHaveCount(0);
    expect((await panel.boundingBox()).height).toBeLessThan(290);
    await panel.getByRole('button', { name: 'Показать описания личностей' }).click();
    await expect(panel.getByText(personas[0].hint, { exact: true })).toBeVisible();
    await panel.getByRole('button', { name: 'Скрыть описания личностей' }).click();
    await page.screenshot({ path: info.outputPath('compact-personas.png'), animations: 'disabled' });
    await page.keyboard.press('Escape');
    await noOverflow(page);
  });

  test('model surface retains aligned icons and dismisses its sole opaque hint', async ({ page, browserName }, info) => {
    await page.getByRole('button', { name: 'Модель: Авто', exact: true }).click();
    const panel = page.getByRole('dialog').filter({ has: page.getByRole('combobox', { name: 'Поиск модели' }) });
    await expect(panel).toHaveCSS('width', '256px');
    await expect(panel.getByText('Система выбирает модель под задачу.', { exact: true })).toHaveCount(0);
    await expect(panel.getByText('Повышенная стоимость', { exact: true })).toHaveCount(0);
    const premium = panel.getByRole('option', { name: /GigaChat-2-Max/ });
    await expect(premium.getByRole('img', { name: 'Повышенная стоимость' })).toBeVisible();
    await expect(premium.getByRole('img', { name: 'Изображения на входе' })).toBeVisible();
    const modelName = await premium.getByText('GigaChat-2-Max', { exact: true }).boundingBox();
    const costIcon = await premium.getByRole('img', { name: 'Повышенная стоимость' }).boundingBox();
    expect(Math.abs((modelName.y + modelName.height / 2) - (costIcon.y + costIcon.height / 2))).toBeLessThan(2);
    await premium.hover();
    await expect(page.getByRole('tooltip')).toContainText('Повышенная стоимость');
    await expect(page.getByRole('tooltip')).toHaveCSS('background-color', 'rgb(10, 12, 18)');
    await expect(page.getByRole('tooltip')).toHaveCSS('opacity', '1');
    await page.screenshot({ path: info.outputPath('compact-model-hint-opaque.png'), animations: 'disabled' });
    if (browserName === 'webkit' && info.project.use.isMobile) {
      // Владельцем клавиатуры в списке остаётся поле поиска.
      await panel.getByRole('combobox', { name: 'Поиск модели' }).press('End');
    } else await page.mouse.wheel(0, 180);
    await expect(page.getByRole('tooltip')).toHaveCount(0);
    await premium.hover();
    await expect(page.getByRole('tooltip')).toContainText('Повышенная стоимость');
    await panel.getByRole('combobox', { name: 'Поиск модели' }).hover();
    await expect(page.getByRole('tooltip')).toHaveCount(0);
    expect((await panel.boundingBox()).height).toBeLessThan(390);
    await page.screenshot({ path: info.outputPath('compact-models.png'), animations: 'disabled' });
    await page.keyboard.press('Escape');
    await noOverflow(page);
  });

  test('strategy hints never stack and selection dismisses the invitation', async ({ page }, info) => {
    await page.getByRole('button', { name: 'Режим: Авто', exact: true }).click();
    const multi = page.getByRole('button', { name: 'Мульти-интент', exact: true });
    const plan = page.getByRole('button', { name: 'Планирование', exact: true });
    await expect(plan).toHaveAttribute('aria-pressed', 'false');
    await multi.focus();
    await expect(page.getByRole('tooltip')).toContainText('Мульти-интент');
    await plan.hover();
    await expect(page.getByRole('tooltip')).toHaveCount(1);
    await expect(page.getByRole('tooltip')).toContainText('Планирование');
    await plan.click();
    await expect(plan).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByRole('tooltip')).toHaveCount(0);
    await page.screenshot({ path: info.outputPath('compact-strategies.png'), animations: 'disabled' });
    await page.keyboard.press('Escape');
    await noOverflow(page);
  });

  test('persona model and mode handoff restores each compact trigger focus', async ({ page }) => {
    const choices = [
      ['Личность: Без личности', 'Выбор личностей'],
      ['Модель: Авто', 'Поиск модели'],
      ['Режим: Авто', 'Выбор режима'],
    ];
    for (const [label, inputName] of choices) {
      const trigger = page.getByRole('button', { name: label, exact: true });
      await trigger.click();
      const input = page.getByRole('combobox', { name: inputName, exact: true });
      await expect(input).toBeVisible();
      await expect(page.getByRole('dialog')).toHaveCount(1);
      await input.focus();
      await page.keyboard.press('Escape');
      await expect(trigger).toBeFocused();
    }
    await noOverflow(page);
  });
});

for (const width of [320, 393, 640]) test(`mobile model palette uses content width without an empty action shelf ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 851 });
  await fixture(page);
  await page.evaluate(() => document.documentElement.style.setProperty('--app-safe-bottom', '34px'));
  const trigger = page.getByRole('button', { name: 'Модель: Авто', exact: true });
  await trigger.click();
  const panel = page.getByRole('dialog', { name: 'Модель ответа', exact: true });
  await expect(panel).toHaveCSS('width', '280px');
  await expect(panel.getByRole('button', { name: 'Закрыть', exact: true })).toHaveCount(0);
  const bounds = await panel.boundingBox();
  expect(Math.abs(bounds.x - (width - bounds.width) / 2)).toBeLessThan(1);
  const close = panel.getByRole('button', { name: 'Закрыть: Модель ответа', exact: true });
  await expect(close).toHaveCSS('width', '44px');
  const row = panel.getByRole('option', { name: /^GigaChat-2-Max/ });
  await expect(row).toHaveCSS('min-height', '44px');
  const list = panel.getByRole('listbox');
  expect(await list.evaluate(element => element.scrollHeight > element.clientHeight)).toBe(true);
  await panel.getByRole('button', { name: 'Показать описания моделей' }).click();
  await expect(panel).toHaveCSS('width', `${Math.min(320, width - 24)}px`);
  await expect(panel.getByText('Повышенная стоимость', { exact: true })).toBeVisible();
  await panel.getByRole('button', { name: 'Скрыть описания моделей' }).click();
  await expect(panel).toHaveCSS('width', '280px');
  if (width === 393) {
    await page.addScriptTag({ content: axe.source });
    const violations = await panel.evaluate(async element => (await window.axe.run(element)).violations
      .filter(item => ['serious', 'critical'].includes(item.impact)));
    expect(violations).toEqual([]);
  }
  await panel.screenshot({ path: info.outputPath(`model-palette-${width}.png`), animations: 'disabled' });
  await close.click();
  await expect(trigger).toBeFocused();
  await noOverflow(page);
});

test('model palette keeps catalog expansion and scrolling inside the compact surface', async ({ page }) => {
  await page.setViewportSize({ width: 393, height: 851 });
  await fixture(page);
  await page.getByRole('button', { name: 'Модель: Авто', exact: true }).click();
  const panel = page.getByRole('dialog', { name: 'Модель ответа', exact: true });
  await expect(panel.getByRole('option')).toHaveCount(61);
  await panel.getByRole('button', { name: /Показать ещё/ }).click();
  await expect(panel.getByRole('option')).toHaveCount(121);
  await expect(panel).toHaveCSS('width', '280px');
  const list = panel.getByRole('listbox');
  await list.evaluate(element => { element.scrollTop = element.scrollHeight; });
  expect(await list.evaluate(element => element.scrollTop > 0)).toBe(true);
  await panel.getByRole('button', { name: 'Закрыть: Модель ответа', exact: true }).click();
});

test('long selections stay bounded and their full name remains available inside the panel', async ({ page }, info) => {
  await page.setViewportSize({ width: 320, height: 851 });
  await fixture(page, { context: true });
  const text = page.getByRole('textbox', { name: 'Сообщение', exact: true });
  await text.fill('Сохранить ввод при выборе длинного названия');
  await page.getByRole('button', { name: 'Модель: Авто', exact: true }).click();
  await page.getByRole('combobox', { name: 'Поиск модели' }).fill('very-long');
  await page.getByRole('option', { name: /very-long-selected-model/ }).click();
  const trigger = page.getByRole('button', { name: `Модель: ${LONG_MODEL.split('/')[1]}`, exact: true });
  const bounds = await trigger.boundingBox();
  expect(bounds.width).toBe(44);
  await expect(trigger).toHaveText('');
  const gauge = await page.getByRole('button', { name: /Контекст заполнен на 0%/ }).boundingBox();
  expect(gauge.x).toBeGreaterThanOrEqual(bounds.x + bounds.width);
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(320);
  await expect(text).toHaveValue('Сохранить ввод при выборе длинного названия');
  await noOverflow(page);
  await page.screenshot({ path: info.outputPath('composer-long-selection.png') });
  await trigger.click();
  const panel = page.getByRole('dialog', { name: 'Модель ответа', exact: true });
  await panel.getByRole('combobox', { name: 'Поиск модели' }).fill('very-long');
  const selected = panel.getByRole('option', { name: /very-long-selected-model/ });
  await expect(selected).toHaveAttribute('aria-selected', 'true');
  await expect(selected.getByText(LONG_MODEL.split('/')[1], { exact: true })).toHaveAttribute('title', LONG_MODEL.split('/')[1]);
  await panel.getByRole('button', { name: 'Показать описания моделей' }).click();
  await expect(selected.getByText(LONG_MODEL.split('/')[1], { exact: true })).toHaveCSS('overflow-wrap', 'anywhere');
  await expect(panel).toHaveCSS('width', '296px');
  await noOverflow(page);
});

test('mobile picker follows keyboard visual viewport without losing search or close action', async ({ page }) => {
  await page.setViewportSize({ width: 393, height: 851 });
  await fixture(page);
  await page.getByRole('button', { name: 'Модель: Авто', exact: true }).click();
  const search = page.getByRole('combobox', { name: 'Поиск модели', exact: true });
  await search.fill('GigaChat');
  // Deterministic viewport fixture, not certification of a device's native keyboard.
  await page.evaluate(() => {
    Object.defineProperty(window.visualViewport, 'height', { configurable: true, value: 400 });
    Object.defineProperty(window.visualViewport, 'offsetTop', { configurable: true, value: 36 });
    window.visualViewport.dispatchEvent(new Event('resize'));
    window.visualViewport.dispatchEvent(new Event('scroll'));
  });
  const dialog = page.getByRole('dialog', { name: 'Модель ответа', exact: true });
  await expect(dialog).toHaveCount(1);
  await expect.poll(async () => {
    const box = await dialog.boundingBox();
    return box.y + box.height;
  }).toBeLessThanOrEqual(436);
  const close = dialog.getByRole('button', { name: 'Закрыть: Модель ответа', exact: true });
  const closeBounds = await close.boundingBox();
  expect(closeBounds.y + closeBounds.height).toBeLessThanOrEqual(436);
  await page.evaluate(() => {
    Object.defineProperty(window.visualViewport, 'offsetTop', { configurable: true, value: 12 });
    window.visualViewport.dispatchEvent(new Event('scroll'));
  });
  await expect.poll(async () => {
    const box = await dialog.boundingBox();
    return box.y + box.height;
  }).toBeLessThanOrEqual(412);
  await expect(search).toHaveValue('GigaChat');
  await expect(search).toBeFocused();
  await page.evaluate(() => {
    delete window.visualViewport.height;
    delete window.visualViewport.offsetTop;
    window.visualViewport.dispatchEvent(new Event('resize'));
  });
  await close.click();
  await expect(page.getByRole('button', { name: 'Модель: Авто', exact: true })).toBeFocused();
});

test('personas keep order, enforce the cap and remain explicitly clearable', async ({ page }) => {
  await fixture(page);
  await page.getByRole('button', { name: 'Личность: Без личности', exact: true }).click();
  await page.getByRole('option', { name: /^Аналитик/ }).click();
  await page.getByRole('option', { name: /^Инженер/ }).click();
  await expect(page.getByRole('option', { name: /^Учёный/ })).toHaveAttribute('aria-disabled', 'true');
  await expect(page.getByText(/^Выбрано 2 из 2(?:\.|$)/)).toBeVisible();
  await expect(page.getByRole('option', { name: /^Аналитик/ })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByRole('option', { name: /^Инженер/ })).toHaveAttribute('aria-selected', 'true');
  await page.getByRole('button', { name: 'Готово', exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'Личность ассистента', exact: true })).toBeHidden();
  await expect(page.getByRole('button', { name: 'Личность: Аналитик + Инженер', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Личность: Аналитик + Инженер', exact: true }).click();
  await page.getByRole('button', { name: 'Без личности', exact: true }).click();
  await expect(page.getByText(/^Выбрано 0 из 2(?:\.|$)/)).toBeVisible();
  await expect(page.getByRole('option', { selected: true })).toHaveCount(0);
});

test('selected picker accents use the existing readable blue foreground', async ({ page }) => {
  await fixture(page);
  const persona = page.getByRole('button', { name: 'Личность: Без личности', exact: true });
  await persona.click();
  await page.getByRole('option', { name: /^Инженер/ }).click();
  const lead = page.getByRole('button', { name: 'Личность: Инженер', exact: true });
  await page.getByRole('button', { name: 'Готово', exact: true }).click();
  // Theme blue.100 is the shared selected foreground (not an undefined ramp key).
  await expect(lead).toHaveCSS('color', 'rgb(199, 211, 255)');
  const model = page.getByRole('button', { name: 'Модель: Авто', exact: true });
  await model.click();
  await page.getByRole('option', { name: /^GigaChat-2-Max/ }).click();
  await expect(page.getByRole('button', { name: 'Модель: GigaChat-2-Max', exact: true }))
    .toHaveCSS('color', 'rgb(199, 211, 255)');
});

test('catalog expansion, search clearing and explicit retry are usable', async ({ page }) => {
  const state = { unavailable: true };
  await fixture(page, state);
  await page.getByRole('button', { name: 'Модель: Авто', exact: true }).click();
  await expect(page.getByText('Каталог временно недоступен. Ваш выбор сохранён.')).toBeVisible();
  state.unavailable = false;
  await page.getByRole('button', { name: 'Повторить загрузку', exact: true }).click();
  await page.getByRole('button', { name: /^Показать ещё/ }).click();
  const search = page.getByRole('combobox', { name: 'Поиск модели', exact: true });
  await search.fill('unknown-model');
  await expect(page.getByText('Ничего не найдено. Измените или очистите поиск.')).toBeVisible();
  await page.getByRole('button', { name: 'Очистить поиск', exact: true }).click();
  await expect(search).toBeFocused();
  await expect(search).toHaveValue('');
});

for (const [name, optionName] of [
  ['Режим: Авто', 'Веб-поиск'],
  ['Личность: Без личности', 'Инженер'],
  ['Модель: Авто', /^GigaChat-2-Max(?:\s|$)/],
]) {
  test(`picker option itself owns an open tooltip: ${name}`, async ({ page }) => {
    await page.setViewportSize({ width: 393, height: 851 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await fixture(page);
    const trigger = page.getByRole('button', { name, exact: true });
    await trigger.click();
    await page.addScriptTag({ content: axe.source });
    const option = page.getByRole('option', { name: optionName, exact: true });
    await option.hover();
    const tooltip = page.getByRole('tooltip');
    await expect(tooltip).toBeVisible();
    await expect(option).toHaveAttribute('aria-describedby', await tooltip.getAttribute('id'));
    expect((await option.boundingBox()).height).toBeGreaterThanOrEqual(44);
    const failures = await page.evaluate(async () => (await window.axe.run(document, {
      runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'] },
    })).violations.filter(item => ['serious', 'critical'].includes(item.impact)));
    expect(failures).toEqual([]);
    await page.mouse.move(0, 0);
    await expect(tooltip).toHaveCount(0);
    await page.keyboard.press('Escape');
    await expect(trigger).toBeFocused();
  });
}

test('open pickers pass axe at short viewport and reduced motion', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await fixture(page);
  for (const name of ['Режим: Авто', 'Личность: Без личности', 'Модель: Авто']) {
    await page.getByRole('button', { name, exact: true }).click();
    await expect(page.getByRole('dialog').last()).toBeVisible();
    await page.addScriptTag({ content: axe.source });
    const failures = await page.evaluate(async () => {
      const report = await window.axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'] } });
      return report.violations.filter((item) => ['serious', 'critical'].includes(item.impact)).map((item) => ({
        id: item.id, targets: item.nodes.map((node) => {
          const element = document.querySelector(node.target[0]);
          return { selector: node.target, tag: element?.tagName, label: element?.getAttribute('aria-label') };
        }),
      }));
    });
    expect(failures).toEqual([]);
    await page.keyboard.press('Escape');
    await noOverflow(page);
  }
});

test('narrow, tablet, 200-percent-equivalent reflow and forced colors keep actions reachable', async ({ page }) => {
  await fixture(page);
  await page.emulateMedia({ forcedColors: 'active', reducedMotion: 'reduce' });
  // 720x450 is the CSS viewport of a 1440x900 screen at 200% browser zoom.
  // This verifies reflow, not the operating system's native zoom/keyboard UI.
  for (const viewport of [{ width: 320, height: 640 }, { width: 900, height: 620 }, { width: 720, height: 450 }]) {
    await page.setViewportSize(viewport);
    await page.getByRole('button', { name: 'Модель: Авто', exact: true }).click();
    const search = page.getByRole('combobox', { name: 'Поиск модели' });
    await search.fill('GigaChat-2');
    await expect(page.getByRole('option', { name: /^GigaChat-2-Max/ })).toBeVisible();
    await page.getByRole('button', { name: 'Очистить поиск', exact: true }).click();
    await expect(search).toBeFocused();
    await search.press('Escape');
    await expect(page.getByRole('button', { name: 'Модель: Авто', exact: true })).toBeFocused();
    await noOverflow(page);
  }
});

test('long composer text does not cover file, voice or send controls', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 640 });
  await fixture(page);
  const text = page.getByRole('textbox', { name: 'Сообщение', exact: true });
  await text.fill(Array.from({ length: 30 }, (_, index) => `Строка ${index + 1}: длинный проверочный текст`).join('\n'));
  const geometry = await text.evaluate((element) => {
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return { scrolls: element.scrollHeight > element.clientHeight,
      left: rect.left + parseFloat(style.paddingLeft),
      right: rect.right - parseFloat(style.paddingRight), resize: style.resize };
  });
  expect(geometry.scrolls).toBe(true);
  const attachment = await page.getByRole('button', { name: 'Прикрепить файл', exact: true })
    .locator('[data-composer-action-surface]').boundingBox();
  expect(attachment.x + attachment.width).toBeLessThanOrEqual(geometry.left);
  for (const name of ['Голосовой ввод', 'Отправить']) {
    const action = await page.getByRole('button', { name, exact: true }).boundingBox();
    expect(action.x).toBeGreaterThanOrEqual(geometry.right);
  }
  expect(geometry.resize).toBe('none');
  await expect(page.getByRole('button', { name: 'Прикрепить файл', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Отправить', exact: true })).toBeEnabled();
  await noOverflow(page);
});

test('voice controls keep their text-safe touch slot through recording, transcription and preview', async ({ page }, info) => {
  await page.setViewportSize({ width: 320, height: 640 });
  await page.addInitScript(() => {
    window.__voiceFixture = { stoppedTracks: 0 };
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: {
      getUserMedia: async () => ({ getTracks: () => [{ stop: () => { window.__voiceFixture.stoppedTracks += 1; } }] }),
    } });
    window.AudioContext = undefined;
    window.webkitAudioContext = undefined;
    window.MediaRecorder = class {
      state = 'inactive';
      start() { this.state = 'recording'; }
      stop() {
        this.state = 'inactive';
        this.ondataavailable?.({ data: new Blob(['SYNTHETIC_AUDIO'], { type: 'audio/webm' }) });
        this.onstop?.();
      }
    };
  });
  await fixture(page);
  let releaseUpload;
  const uploadReady = new Promise((resolve) => { releaseUpload = resolve; });
  let uploads = 0;
  await page.route('**/api/chats/upload', async (route) => {
    uploads += 1;
    await uploadReady;
    await route.fulfill({ json: { file_id: 'voice-fixture', filename: 'voice.webm', file_type: 'audio', extracted_text: 'Проверочный голос' } });
  });
  const input = page.getByRole('textbox', { name: 'Сообщение', exact: true });
  const draft = 'Текст, который не должен пересекаться с кнопками.\n'.repeat(12);
  await input.fill(draft);
  const checkSlot = async (control) => {
    const box = await control.boundingBox();
    expect(box.width).toBe(44);
    expect(box.height).toBe(44);
    await expect(control.locator('[data-composer-action-surface]')).toHaveCSS('width', '32px');
    await expect(control.locator('[data-composer-action-surface]')).toHaveCSS('height', '32px');
    const textRight = await input.evaluate((element) => element.getBoundingClientRect().right - parseFloat(getComputedStyle(element).paddingRight));
    expect(box.x).toBeGreaterThanOrEqual(textRight);
    await noOverflow(page);
    await expect(input).toHaveValue(draft);
  };
  const microphone = page.getByRole('button', { name: 'Голосовой ввод', exact: true });
  await checkSlot(microphone);
  await microphone.click();
  const stop = page.getByRole('button', { name: 'Остановить запись', exact: true });
  await checkSlot(stop);
  await expect(stop.getByRole('timer')).toBeVisible();
  await expect(stop).toHaveAccessibleDescription(/\d+:\d{2}/);
  await page.addScriptTag({ content: axe.source });
  const voiceA11yFailures = await page.evaluate(async () => {
    const report = await window.axe.run(document.querySelector('[data-composer-container]'), {
      runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'] },
    });
    return report.violations.filter((item) => ['serious', 'critical'].includes(item.impact)).map((item) => item.id);
  });
  expect(voiceA11yFailures).toEqual([]);
  await page.screenshot({ path: info.outputPath('voice-recording-320.png') });
  await stop.click();
  await checkSlot(page.getByRole('status', { name: 'Распознаю голос…', exact: true }));
  releaseUpload();
  await expect(page.getByText('Проверочный голос', { exact: true })).toBeVisible();
  await checkSlot(microphone);
  expect(uploads).toBe(1);
  expect(await page.evaluate(() => window.__voiceFixture.stoppedTracks)).toBe(1);
  const edit = page.getByRole('button', { name: 'Дописать в поле ввода', exact: true });
  for (const action of [edit, page.getByRole('button', { name: 'Убрать голосовое', exact: true })]) {
    const bounds = await action.boundingBox();
    expect(bounds.width).toBe(44);
    expect(bounds.height).toBe(44);
  }
  await edit.click();
  await expect(input).toHaveValue(`${draft}Проверочный голос`);
});

test('model choice remains usable inside the existing profile drawer', async ({ page }) => {
  await fixture(page);
  await page.getByRole('button', { name: 'Меню аккаунта', exact: true }).click();
  await page.getByRole('menuitem', { name: /^Профиль/ }).click();
  const profile = page.getByRole('dialog', { name: 'Профиль', exact: true });
  const trigger = profile.getByRole('button', { name: 'Модель: Авто', exact: true });
  await trigger.scrollIntoViewIfNeeded();
  await trigger.click();
  const search = page.getByRole('combobox', { name: 'Поиск модели', exact: true });
  await search.fill('GigaChat-2-Max');
  await page.getByRole('option', { name: /^GigaChat-2-Max/ }).click();
  await expect(profile.getByRole('button', { name: 'Модель: GigaChat-2-Max', exact: true })).toBeVisible();
});
