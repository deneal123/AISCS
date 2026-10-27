// Даже самостоятельный запуск fixture не должен создать незащищённые соединения.
require('../preload.cjs');
const assert = require('node:assert/strict');
const net = require('node:net');
const child = require('node:child_process');
const { promisify } = require('node:util');

async function probe() {
  assert.throws(() => net.connect({ host: '192.168.1.10', port: 5038 }), { code: 'GPTHUB_VIEWER_SCOPE' });
  assert.throws(() => net.connect({ host: '127.0.0.1', port: 5037 }), { code: 'GPTHUB_VIEWER_SCOPE' });
  assert.throws(() => child.exec('echo forbidden'), { code: 'GPTHUB_VIEWER_SCOPE' });
  assert.throws(() => child.execFile('unrelated.exe', ['--version']), { code: 'GPTHUB_VIEWER_SCOPE' });
  assert.throws(() => child.spawn(process.env.GPTHUB_VIEWER_ADB, ['-s', 'other', 'shell', 'id']),
    { code: 'GPTHUB_VIEWER_SCOPE' });
  assert.throws(() => require('node-pty'), { code: 'GPTHUB_VIEWER_SCOPE' });

  const result = await promisify(child.execFile)(process.execPath, ['--version']);
  assert.match(result.stdout, /^v\d+\./);
  assert.equal(result.stderr, '');
  const server = net.createServer(socket => socket.end('ready'));
  await new Promise(resolve => server.listen(0, '0.0.0.0', resolve));
  assert.equal(server.address().address, '127.0.0.1');
  try {
    const received = await new Promise((resolve, reject) => {
      const socket = net.connect({ host: '127.0.0.1', port: server.address().port });
      let body = '';
      socket.on('data', chunk => { body += chunk; });
      socket.on('end', () => resolve(body));
      socket.on('error', reject);
    });
    assert.equal(received, 'ready');
  } finally { await new Promise(resolve => server.close(resolve)); }
  process.stdout.write('preload integration passed\n');
}

probe().catch(error => { process.stderr.write(`${error.stack}\n`); process.exitCode = 1; });
