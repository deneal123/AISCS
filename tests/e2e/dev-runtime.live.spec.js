const { test, expect } = require('@playwright/test');

test.skip(process.env.E2E_LIVE_DEV_RUNTIME !== '1', 'Opt-in native dev-server check, not a production expectation.');
test.use({ serviceWorkers: 'block' });

test('hot reload connects to the exposed frontend port without masking console errors', async ({ page, baseURL }) => {
  const sockets = [];
  const errors = [];
  page.on('websocket', (socket) => {
    if (new URL(socket.url()).pathname !== '/ws') return;
    const state = { url: socket.url(), types: [] };
    sockets.push(state);
    socket.on('framereceived', ({ payload }) => {
      try { const frame = JSON.parse(String(payload)); state.types.push(frame.type); } catch { /* Ignore non-JSON transport frames. */ }
    });
    socket.on('socketerror', () => errors.push('socket_error'));
  });
  await page.route('https://fonts.googleapis.com/**', (route) => route.fulfill({ contentType: 'text/css', body: '' }));
  await page.route('https://fonts.gstatic.com/**', (route) => route.abort());
  // Real HMR socket, no auth/account/model requests to product services.
  await page.route('**/api/**', (route) => route.fulfill({ status: 401, json: { code: 'unauthorized' } }));
  await page.goto('/login');
  await expect.poll(() => sockets.some((socket) => socket.types.includes('hash') || socket.types.includes('ok'))).toBe(true);
  const expected = new URL(baseURL);
  for (const socket of sockets) {
    const url = new URL(socket.url);
    expect(url.hostname).toBe(expected.hostname);
    expect(url.port).toBe(expected.port);
    expect(url.protocol).toBe(expected.protocol === 'https:' ? 'wss:' : 'ws:');
  }
  expect(errors).toEqual([]);
});
