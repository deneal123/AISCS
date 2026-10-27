// Ограничения применяются до загрузки неизменённого стороннего приложения.
const path = require('node:path');
const net = require('node:net');
const dgram = require('node:dgram');
const child = require('node:child_process');
const moduleApi = require('node:module');
const { promisify } = require('node:util');
const policy = require('./policy.cjs');

const expectedAdb = process.env.GPTHUB_VIEWER_ADB;
if (!expectedAdb || !path.isAbsolute(expectedAdb)) throw policy.refused();
const identity = file => path.resolve(file).toLowerCase();
const adbIdentity = identity(expectedAdb);
const allowedNodes = [process.execPath, process.env.GPTHUB_VIEWER_NODE].filter(Boolean).map(identity);

const originalListen = net.Server.prototype.listen;
net.Server.prototype.listen = function (...args) {
  return originalListen.apply(this, policy.localListenArgs(args));
};
const originalConnect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function (...args) {
  policy.localConnection(args);
  return originalConnect.apply(this, args);
};
dgram.createSocket = () => { throw policy.refused(); };

function invocation(file, args, options, callback) {
  if (!Array.isArray(args)) {
    callback = options;
    options = args;
    args = [];
  }
  if (typeof options === 'function') {
    callback = options;
    options = {};
  }
  let safeArgs;
  if (identity(file) === adbIdentity) safeArgs = policy.adbArgs(args);
  else if (allowedNodes.includes(identity(file))
    && args.length === 1 && ['-v', '--version'].includes(args[0])) safeArgs = args;
  else throw policy.refused();
  if (options?.shell) throw policy.refused();
  return { file, args: safeArgs, callback, options: { ...options,
    windowsHide: true, env: policy.childEnvironment(options?.env || process.env) } };
}

const originalExecFile = child.execFile;
child.execFile = function (file, args, options, callback) {
  const call = invocation(file, args, options, callback);
  const complete = typeof call.callback === 'function' ? (error, stdout, stderr) =>
    call.callback(error, policy.deviceOutput(Array.isArray(args) ? args : [], stdout), stderr) : undefined;
  return originalExecFile(call.file, call.args, call.options, complete);
};
// Node promisify(execFile) обязан сохранить обе части результата, не обойти policy.
child.execFile[promisify.custom] = (...args) => new Promise((resolve, reject) => {
  child.execFile(...args, (error, stdout, stderr) => {
    if (error) { error.stdout = stdout; error.stderr = stderr; reject(error); }
    else resolve({ stdout, stderr });
  });
});
for (const method of ['spawn', 'spawnSync', 'execFileSync']) {
  const original = child[method];
  child[method] = function (file, args, options) {
    const call = invocation(file, args, options);
    return original(call.file, call.args, call.options);
  };
}
for (const method of ['exec', 'execSync', 'fork']) {
  child[method] = () => { throw policy.refused(); };
}

// Терминал с native node-pty не нужен для просмотра и мог бы обойти child policy.
const originalLoad = moduleApi._load;
moduleApi._load = function (request, ...rest) {
  if (request === 'node-pty' || /[/\\]node-pty[/\\]|[/\\]pty\.node$/i.test(request)) throw policy.refused();
  return originalLoad.call(this, request, ...rest);
};
moduleApi.syncBuiltinESMExports();
