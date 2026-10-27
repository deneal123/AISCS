const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

test('настоящий Node preload ограничивает сокеты/процессы и сохраняет promisify', () => {
  const result = spawnSync(process.execPath, [
    '--require', path.resolve(__dirname, '../preload.cjs'),
    path.resolve(__dirname, 'preload-probe.cjs'),
  ], { encoding: 'utf8', windowsHide: true, timeout: 10000,
    env: { ...process.env, GPTHUB_VIEWER_ADB: path.resolve(__dirname, 'never-executed-adb.exe') } });
  assert.equal(result.error, undefined);
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /preload integration passed/);
});
