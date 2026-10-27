const { test } = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');

const enabled = process.env.GPTHUB_VIEWER_HTTP_ACCEPTANCE === '1';
function request(path, headers = {}) {
  return new Promise((resolve, reject) => {
    const req = http.get({ host: '127.0.0.1', port: 8099, path,
      headers: { Host: 'localhost:8099', ...headers } }, res => {
      let body = '';
      res.on('data', chunk => { body += chunk; });
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body }));
    });
    req.setTimeout(3000, () => req.destroy(new Error('Локальный HTTP не ответил')));
    req.on('error', reject);
  });
}

test('локальный viewer: HTML, cookie, Host/Origin и выбранная конфигурация', { skip: !enabled }, async () => {
  const root = await request('/');
  assert.equal(root.status, 200);
  assert.match(root.body, /<script/);
  const cookie = (root.headers['set-cookie'] || []).map(value => value.split(';')[0]).join('; ');
  assert.notEqual(cookie, '');
  // GET /api/config — документированный loopback bootstrap без cookie.
  assert.equal((await request('/api/dependencies')).status, 403);
  assert.equal((await request('/api/config', { Cookie: cookie, Origin: 'https://evil.example' })).status, 403);
  assert.equal((await request('/', { Host: 'evil.example:8099' })).status, 403);
  const config = await request('/api/config', { Cookie: cookie, Origin: 'http://localhost:8099' });
  assert.equal(config.status, 200);
  const value = JSON.parse(config.body);
  assert.equal(value.config.webPort, 8099);
  assert.equal(value.config.autoUpdate, false);
  assert.equal(value.runtime.appVersion, '0.5.10');
  const dependencies = await request('/api/dependencies', { Cookie: cookie, Origin: 'http://localhost:8099' });
  assert.equal(dependencies.status, 200);
  const installed = JSON.parse(dependencies.body);
  for (const name of ['nodejs', 'adb', 'scrcpy-server']) {
    assert.ok(installed.find(item => item.name === name)?.installedVersion, `Не распознана зависимость ${name}`);
  }
  const updater = await request('/api/updates/status', { Cookie: cookie, Origin: 'http://localhost:8099' });
  assert.equal(updater.status, 200);
  assert.equal(JSON.parse(updater.body).isInstalled, false);
});

test('WebSocket с чужим Origin отклоняется до выбора устройства', { skip: !enabled }, async () => {
  const result = await request('/', { Connection: 'Upgrade', Upgrade: 'websocket',
'Sec-WebSocket-Version': '13', 'Sec-WebSocket-Key': require('node:crypto').randomBytes(16).toString('base64'), Origin: 'https://evil.example' });
  assert.equal(result.status, 403);
});
