const { test } = require('node:test');
const assert = require('node:assert/strict');
const policy = require('../policy.cjs');

test('все TCP-listen перегрузки ограничены IPv4 loopback', () => {
  const callback = () => {};
  assert.deepEqual(policy.localListenArgs([8099, callback]), [8099, '127.0.0.1', callback]);
  assert.deepEqual(policy.localListenArgs([8099, '0.0.0.0', 128, callback]), [8099, '127.0.0.1', 128, callback]);
  assert.deepEqual(policy.localListenArgs([{ port: 8099, host: '::', exclusive: true }, callback]),
    [{ port: 8099, host: '127.0.0.1', exclusive: true }, callback]);
  for (const args of [[{ fd: 3 }], ['arbitrary.pipe'], [{ path: 'arbitrary.pipe' }], [-1]]) {
    assert.throws(() => policy.localListenArgs(args), { code: 'GPTHUB_VIEWER_SCOPE' });
  }
});

test('TCP допускает loopback, но не LAN, DNS, общий ADB или сокет-путь', () => {
  for (const args of [[5038, '127.0.0.1'], [{ host: 'localhost', port: 5038 }],
    [[{ host: '127.0.0.1', port: 40000 }, () => {}]]]) assert.doesNotThrow(() => policy.localConnection(args));
  for (const args of [[5037, '127.0.0.1'], [{ host: 'api.github.com', port: 443 }],
    [5038, '192.168.1.10'], [{ path: 'arbitrary.pipe' }], [{ host: '127.0.0.1', port: 0 }]]) {
    assert.throws(() => policy.localConnection(args), { code: 'GPTHUB_VIEWER_SCOPE' });
  }
});

test('ADB адресуется только нашему serial и собственному серверу', () => {
  for (const args of [['version'], ['--version'], ['devices', '-l'], ['kill-server'],
    ['-s', 'emulator-5580', 'shell', 'wm', 'size'],
    ['-s', 'emulator-5580', 'forward', 'tcp:0', 'localabstract:scrcpy']]) {
    assert.deepEqual(policy.adbArgs(args), ['-H', '127.0.0.1', '-P', '5038', ...args]);
  }
  assert.deepEqual(policy.adbArgs(['start-server']), ['-P', '5038', '--one-device', 'emulator-5580', 'start-server']);
  for (const args of [['shell', 'id'], ['-s', 'another-device', 'shell', 'id'],
    ['-e', 'shell', 'id'], ['-P', '5037', 'kill-server'], ['-a', 'start-server'],
    ['connect', '192.168.1.10'], ['mdns', 'services'], ['devices', '-s', 'other'],
    ['-s', 'emulator-5580', 'reboot']]) {
    assert.throws(() => policy.adbArgs(args), { code: 'GPTHUB_VIEWER_SCOPE' });
  }
});

test('настройки дочернего процесса не возвращают общий ADB и auto-connect', () => {
  const env = policy.childEnvironment({ ANDROID_ADB_SERVER_PORT: '5037', ADB_MDNS_AUTO_CONNECT: 'all', example: 'kept' });
  assert.equal(env.ADB_SERVER_SOCKET, 'tcp:localhost:5038');
  assert.equal(env.ANDROID_ADB_SERVER_PORT, '5038');
  assert.equal(env.ADB_MDNS_AUTO_CONNECT, '0');
  assert.equal(env.example, 'kept');
});

test('список устройств не раскрывает чужие serial', () => {
  const output = 'List of devices attached\r\nother\tdevice\r\nemulator-5580\tdevice product:example\r\nemulator-55800\tdevice\r\n';
  const expected = 'List of devices attached\nemulator-5580\tdevice product:example\n';
  assert.equal(policy.deviceOutput(['devices', '-l'], output), expected);
  assert.equal(policy.deviceOutput(['devices'], Buffer.from(output)).toString(), expected);
  assert.equal(policy.deviceOutput(['version'], 'unchanged'), 'unchanged');
});
