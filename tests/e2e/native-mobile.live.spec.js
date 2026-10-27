const { test, expect, _android, request } = require('@playwright/test');
const fs = require('node:fs/promises');
const { execFileSync } = require('node:child_process');
const { ADB_PORT, SERIAL, nativeAdb, ensureNativeDevRoutes } = require('./helpers/nativeAndroid');

const enabled = process.env.E2E_NATIVE_ANDROID === '1';
const token = process.env.E2E_AUTH_TOKEN || '';
const serial = process.env.E2E_ANDROID_SERIAL || 'emulator-5580';
const baseURL = process.env.E2E_BASE_URL || 'http://localhost:3001';
const apiURL = process.env.E2E_NATIVE_API_URL || 'http://localhost:8001';

test.use({ trace: 'off', video: 'off' });
test.setTimeout(90_000);

test('нативный Android: клавиатура не перекрывает ввод и не теряет черновик', async ({}, info) => {
  test.skip(!enabled || !token, 'Нужны выделенный Android-эмулятор и токен синтетического dev-пользователя.');
  for (const [address, port] of [[baseURL, '3001'], [apiURL, '8001']]) {
    const url = new URL(address);
    expect(['localhost', '127.0.0.1']).toContain(url.hostname);
    expect(url.protocol).toBe('http:');
    expect(url.port).toBe(port);
    expect(url.username + url.password + url.search + url.hash).toBe('');
    expect(url.pathname).toBe('/');
  }
  // Одного loopback недостаточно: на нём может находиться туннель в production.
  for (const [service, containerPort, hostPort] of [['frontend', '3000', '3001'], ['backend', '8000', '8001']]) {
    const template = `{{.State.Running}}|{{index .Config.Labels "com.docker.compose.project"}}|{{(index (index .NetworkSettings.Ports "${containerPort}/tcp") 0).HostPort}}`;
    const identity = execFileSync('docker', ['inspect', '--format', template, `gpthub-dev-${service}-1`],
      { encoding: 'utf8', windowsHide: true }).trim();
    expect(identity, 'Порт должен принадлежать работающему сервису локального dev-проекта').toBe(`true|gpthub-dev|${hostPort}`);
  }
  expect(serial).toBe(SERIAL);
  const devices = await _android.devices({ host: '127.0.0.1', port: ADB_PORT, omitDriverInstall: true });
  const device = devices.find(candidate => candidate.serial() === serial);
  expect(device, 'Созданный для GPTHub эмулятор должен быть доступен через ADB').toBeTruthy();
  const api = await request.newContext({ baseURL: apiURL, extraHTTPHeaders: { Authorization: `Bearer ${token}` } });
  let context;
  let threadId;
  try {
    const avdName = nativeAdb('emu', 'avd', 'name').split(/\r?\n/)[0].trim();
    expect(avdName, 'Проверяется только созданный для GPTHub телефон, не другое устройство').toBe('GPTHub_Mobile_API35');
    // Оставляем ожидаемые dev-маршруты и для последующего просмотра того же телефона.
    ensureNativeDevRoutes();
    const created = await api.post('/api/chats/', { data: { title: 'Нативная мобильная приёмка: клавиатура' } });
    expect(created.status()).toBe(201);
    const createdId = (await created.json()).thread_id;
    expect(createdId).toMatch(/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i);
    threadId = createdId;
    context = await device.launchBrowser({ pkg: 'com.android.chrome' });
    await context.addCookies([{ name: 'auth_token', value: token, url: baseURL }]);
    await context.addInitScript(value => {
      localStorage.setItem('telerag:isAuthenticated', 'true');
      localStorage.setItem('auth_token', value);
    }, token);
    const page = context.pages()[0] || await context.newPage();
    await page.goto(`${baseURL}/chat/${threadId}`, { waitUntil: 'domcontentloaded' });
    const input = page.getByRole('textbox', { name: 'Сообщение', exact: true });
    await expect(input).toBeVisible();
    const viewportHeight = () => page.evaluate(() => visualViewport.height);
    const initialHeight = await viewportHeight();
    await fs.writeFile(info.outputPath('android-chat-before-keyboard.png'), await device.screenshot());
    await input.tap();
    // Здесь нет подмены visualViewport: высоту меняет настоящая клавиатура Android.
    await expect.poll(viewportHeight).toBeLessThan(initialHeight - 100);
    const focusedHeight = (await input.boundingBox()).height;
    await input.fill('ф');
    await expect.poll(async () => (await input.boundingBox()).height).toBe(focusedHeight);
    const geometry = await page.evaluate(() => {
      const shell = document.querySelector('[data-product-viewport]').getBoundingClientRect();
      return { top: shell.top, bottom: shell.bottom, viewportTop: visualViewport.offsetTop,
        viewportBottom: visualViewport.offsetTop + visualViewport.height,
        scrollWidth: document.documentElement.scrollWidth, width: innerWidth };
    });
    expect(geometry.top).toBeGreaterThanOrEqual(geometry.viewportTop - 1);
    expect(geometry.bottom).toBeLessThanOrEqual(geometry.viewportBottom + 1);
    expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.width);
    await input.fill('Мобильный черновик\n'.repeat(24));
    await expect(input).toHaveCSS('overflow-y', 'auto');
    await fs.writeFile(info.outputPath('android-chat-with-keyboard.png'), await device.screenshot());
    await device.shell('input keyevent 4');
    await expect.poll(viewportHeight).toBeGreaterThan(initialHeight - 80);
    await expect(input).toHaveValue('Мобильный черновик\n'.repeat(24));
    await fs.writeFile(info.outputPath('android-chat-after-keyboard.png'), await device.screenshot());
    // Отправка сообщения, платные вызовы и запуск агента не выполняются.
  } finally {
    try {
      await context?.close();
    } finally {
      try {
        if (threadId) {
          const removed = await api.delete(`/api/chats/${threadId}`);
          expect(removed.ok(), 'Удаляется только чат, созданный этим тестом').toBeTruthy();
        }
      } finally {
        await api.dispose();
        await device.close();
      }
    }
  }
});
