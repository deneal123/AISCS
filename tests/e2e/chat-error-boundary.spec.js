const { test, expect } = require('@playwright/test');

test.use({ serviceWorkers: 'block' });
const THREAD = 'safe-error-fixture';
const SENTINEL = 'PRIVATE_INTEGRATION_EXCEPTION_BODY';

async function installApi(page) {
  await page.addInitScript(() => {
    localStorage.setItem('telerag:isAuthenticated', 'true');
    localStorage.setItem('auth_token', 'safe-error-fixture-token');
  });
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    let json = {};
    if (path === '/api/profile/me') json = { id: 'fixture-user', email: 'errors@example.test', permissions: [] };
    if (path === '/api/chats/') json = { chats: [{ thread_id: THREAD, title: 'Безопасные ошибки' }] };
    if (path === `/api/chats/${THREAD}`) json = { messages: [] };
    if (path.endsWith('/trace')) json = { traces: {} };
    if (path.endsWith('/models/catalog')) json = { models: [], providers: [] };
    if (path.endsWith('/models')) json = { models: [] };
    if (path.endsWith('/personas')) json = { personas: [] };
    if (path.endsWith('/transcription/config')) json = { enabled: false };
    if (path === '/api/billing/balance') json = { balance: 1000 };
    await route.fulfill({ json });
  });
}

for (const [code, message] of [
  ['timeout', 'Истекло время ожидания ответа.'],
  ['auth', 'Нет доступа к выбранному провайдеру.'],
  ['insufficient_funds', 'Недостаточно средств на балансе.'],
  ['constructor', 'Выполнение завершилось с ошибкой.'],
]) {
  test(`wire error ${code} uses only its safe label without dispatching another job`, async ({ page }) => {
    await installApi(page);
    let requests = 0;
    await page.routeWebSocket('**/api/**', (socket) => {
      socket.onMessage((raw) => {
        const request = JSON.parse(raw);
        if (request.type !== 'message') return;
        requests += 1;
        socket.send(JSON.stringify({ type: 'job_created', job_id: 'safe-fixture-job' }));
        socket.send(JSON.stringify({ type: 'error', job_id: 'safe-fixture-job', code,
          message: SENTINEL, error: SENTINEL, data: SENTINEL }));
      });
    });
    await page.goto(`/chat/${THREAD}`);
    await expect(page.getByRole('status', { name: 'На связи', exact: true })).toBeVisible({ timeout: 15000 });
    await page.getByRole('textbox', { name: 'Сообщение', exact: true }).fill('Синтетическая проверка ошибки');
    await page.getByRole('button', { name: 'Отправить', exact: true }).click();
    await expect(page.getByText(message, { exact: true }).first()).toBeVisible();
    await expect(page.getByRole('button', { name: 'Остановить генерацию', exact: true })).toHaveCount(0);
    await expect(page.locator('body')).not.toContainText(SENTINEL);
    await expect(page.locator('body')).not.toContainText('Ошибка чата:');
    expect(requests).toBe(1);
  });
}

test('local socket constructor failure stays bounded in visible feedback', async ({ page }) => {
  await installApi(page);
  await page.addInitScript((marker) => {
    const NativeWebSocket = window.WebSocket;
    window.WebSocket = class extends NativeWebSocket {
      constructor(url, protocols) {
        // Fault only product sockets; webpack's dev/HMR socket is not the subject.
        if (new URL(url, location.href).pathname.startsWith('/api/')) throw new Error(marker);
        super(url, protocols);
      }
    };
  }, SENTINEL);
  await page.goto(`/chat/${THREAD}`);
  await expect(page.getByText('Сервис временно недоступен.', { exact: true }).first()).toBeVisible();
  await expect(page.locator('body')).not.toContainText(SENTINEL);
  await expect(page.locator('body')).not.toContainText('WebSocket connection error');
});
