const path = require('node:path');
const { execFileSync } = require('node:child_process');

const ADB_PORT = 5038;
const SERIAL = 'emulator-5580';

function nativeAdb(...args) {
  const sdkRoot = process.env.ANDROID_SDK_ROOT || path.join(process.env.LOCALAPPDATA, 'Android', 'Sdk');
  return execFileSync(path.join(sdkRoot, 'platform-tools', 'adb.exe'),
    ['-H', '127.0.0.1', '-P', String(ADB_PORT), '-s', SERIAL, ...args],
    { encoding: 'utf8', windowsHide: true, timeout: 5000 }).trim();
}

// Не перезаписываем существующий пользовательский reverse с другим назначением.
function ensureNativeDevRoutes(run = nativeAdb) {
  const mappings = run('reverse', '--list').split(/\r?\n/).filter(Boolean)
    .map(line => line.trim().split(/\s+/).slice(-2));
  const addresses = ['tcp:3001', 'tcp:8001'];
  for (const address of addresses) {
    const existing = mappings.find(([remote]) => remote === address);
    if (existing && existing[1] !== address) throw new Error(`Android reverse ${address} уже принадлежит другому назначению`);
  }
  for (const address of addresses) {
    if (!mappings.some(([remote]) => remote === address)) run('reverse', '--no-rebind', address, address);
  }
}

module.exports = { ADB_PORT, SERIAL, nativeAdb, ensureNativeDevRoutes };
