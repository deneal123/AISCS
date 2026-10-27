const { test, expect } = require('@playwright/test');
test.use({ serviceWorkers: 'block' });
const THREAD = 'voice-owner-a';
const OTHER = 'voice-owner-b';
const deferred = () => {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
};

async function fixture(page, { pendingPermission = false, holdUpload = false } = {}) {
  const delivery = deferred();
  const settled = deferred();
  const state = { uploads: 0, delivery, settled };
  await page.route('https://fonts.googleapis.com/**', (route) => route.fulfill({ contentType: 'text/css', body: '' }));
  await page.route('https://fonts.gstatic.com/**', (route) => route.abort());
  await page.addInitScript(({ pending }) => {
    localStorage.setItem('telerag:isAuthenticated', 'true');
    localStorage.setItem('auth_token', 'voice-owner-fixture-token');
    const capture = { requests: 0, stoppedTracks: 0, recorders: 0, recorderStops: 0, grantPermission: null };
    window.__captureFixture = capture;
    const stream = () => ({ getTracks: () => [{ stop: () => { capture.stoppedTracks += 1; } }] });
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: {
      getUserMedia: () => {
        capture.requests += 1;
        return pending ? new Promise((resolve) => { capture.grantPermission = () => resolve(stream()); }) : Promise.resolve(stream());
      },
    } });
    window.AudioContext = undefined;
    window.webkitAudioContext = undefined;
    window.MediaRecorder = class {
      state = 'inactive';
      constructor() { capture.recorders += 1; }
      start() { this.state = 'recording'; }
      stop() {
        capture.recorderStops += 1;
        this.state = 'inactive';
        this.ondataavailable?.({ data: new Blob(['SYNTHETIC_CAPTURE'], { type: 'audio/webm' }) });
        this.onstop?.();
      }
    };
  }, { pending: pendingPermission });
  await page.routeWebSocket('**/api/**', () => {});
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    let json = {};
    if (path === '/api/profile/me') json = { id: 'voice-user', email: 'voice@example.test', permissions: [] };
    if (path === '/api/chats/') json = { chats: [
      { thread_id: THREAD, title: 'Голосовой исходный тред' }, { thread_id: OTHER, title: 'Другой голосовой тред' },
    ] };
    if ([`/api/chats/${THREAD}`, `/api/chats/${OTHER}`].includes(path)) json = { messages: [] };
    if (path.endsWith('/trace')) json = { traces: {} };
    if (path.endsWith('/personas')) json = { personas: [] };
    if (path.endsWith('/models/catalog')) json = { models: [], providers: [] };
    if (path.endsWith('/transcription/config')) json = { enabled: false };
    if (path.endsWith('/work')) json = {
      contract_version: 2, workspace: { state: 'absent', revision: '', entries: [], history: [] },
      library: { state: 'ready', items: [], next_cursor: null },
      room: { state: 'absent', leases: [], activity: [], control: { state: 'running' } },
    };
    if (path === '/api/chats/upload') {
      state.uploads += 1;
      if (holdUpload) await delivery.promise;
      if (route.request().failure()) { settled.resolve(); return; }
      json = { file_id: 'voice-owner-file', filename: 'voice.webm', file_type: 'audio', extracted_text: 'Принятый голосовой текст' };
      await route.fulfill({ json });
      settled.resolve();
      return;
    }
    await route.fulfill({ json });
  });
  await page.goto(`/chat/${THREAD}`);
  await expect(page.getByRole('button', { name: 'Голосовой ввод', exact: true })).toBeVisible();
  return state;
}

async function changeThread(page) {
  const destination = page.getByRole('button', { name: 'Другой голосовой тред', exact: true });
  if (!await destination.isVisible()) await page.getByRole('button', { name: 'Меню', exact: true }).click();
  await destination.click();
  await expect(page).toHaveURL(new RegExp(`/chat/${OTHER}$`));
  await expect(page.getByRole('button', { name: 'Голосовой ввод', exact: true })).toBeVisible();
}

test('late microphone permission cannot start recording in another thread', async ({ page }) => {
  const state = await fixture(page, { pendingPermission: true });
  await page.getByRole('button', { name: 'Голосовой ввод', exact: true }).click();
  await expect(page.getByRole('status', { name: 'Ожидаю разрешения микрофона…' })).toBeVisible();
  await changeThread(page);
  const input = page.getByRole('textbox', { name: 'Сообщение', exact: true });
  await input.fill('Новый черновик');
  await page.evaluate(() => window.__captureFixture.grantPermission());
  await expect.poll(() => page.evaluate(() => window.__captureFixture.stoppedTracks)).toBe(1);
  expect(await page.evaluate(() => window.__captureFixture.recorders)).toBe(0);
  expect(state.uploads).toBe(0);
  await expect(input).toHaveValue('Новый черновик');
});

test('thread navigation retires active recording without starting STT', async ({ page }) => {
  const state = await fixture(page);
  await page.getByRole('button', { name: 'Голосовой ввод', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Остановить запись', exact: true })).toBeVisible();
  await changeThread(page);
  expect(await page.evaluate(() => window.__captureFixture.stoppedTracks)).toBe(1);
  expect(await page.evaluate(() => window.__captureFixture.recorderStops)).toBe(1);
  expect(state.uploads).toBe(0);
  await expect(page.getByRole('status', { name: 'Распознаю голос…' })).toHaveCount(0);
});

test('leaving a pending transcription aborts observation without injecting its result into the next draft', async ({ page }) => {
  const state = await fixture(page, { holdUpload: true });
  await page.getByRole('button', { name: 'Голосовой ввод', exact: true }).click();
  await page.getByRole('button', { name: 'Остановить запись', exact: true }).click();
  await expect.poll(() => state.uploads).toBe(1);
  const aborted = page.waitForEvent('requestfailed', { predicate: (request) => new URL(request.url()).pathname === '/api/chats/upload' });
  await changeThread(page);
  await aborted;
  const input = page.getByRole('textbox', { name: 'Сообщение', exact: true });
  await input.fill('Не заменять этот черновик');
  state.delivery.resolve();
  await state.settled.promise;
  await expect(input).toHaveValue('Не заменять этот черновик');
  await expect(page.locator('body')).not.toContainText('Принятый голосовой текст');
  expect(state.uploads).toBe(1);
});

test('Chat and Work retain the same pending capture owner and composer text', async ({ page }) => {
  const state = await fixture(page, { pendingPermission: true });
  const input = page.getByRole('textbox', { name: 'Сообщение', exact: true });
  await input.fill('Сохранённый текст');
  await page.getByRole('button', { name: 'Голосовой ввод', exact: true }).click();
  await page.getByRole('button', { name: 'Работа', exact: true }).click();
  await page.getByRole('button', { name: 'Чат', exact: true }).click();
  await expect(input).toHaveValue('Сохранённый текст');
  await expect(page.getByRole('status', { name: 'Ожидаю разрешения микрофона…' })).toBeVisible();
  await page.evaluate(() => window.__captureFixture.grantPermission());
  await page.getByRole('button', { name: 'Остановить запись', exact: true }).click();
  await expect(page.getByText('Принятый голосовой текст', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => window.__captureFixture.requests)).toBe(1);
  expect(state.uploads).toBe(1);
  await expect(input).toHaveValue('Сохранённый текст');
});
