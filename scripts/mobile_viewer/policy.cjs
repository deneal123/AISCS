const HOST = '127.0.0.1';
const HTTP_PORT = 8099;
const ADB_PORT = 5038;
const SERIAL = 'emulator-5580';

function refused() {
  const error = new Error('Локальный просмотрщик: операция вне разрешённой области');
  error.code = 'GPTHUB_VIEWER_SCOPE';
  return error;
}

function loopback(host) {
  return [HOST, 'localhost', '::1', '[::1]'].includes(String(host).toLowerCase());
}

// Сохраняем перегрузки listen(port, host?, backlog?, callback) и listen(options).
function localListenArgs(args) {
  const [first, ...rest] = args;
  if (first && typeof first === 'object' && !Array.isArray(first)) {
    if (first.path || first.fd != null || !Number.isInteger(first.port)) throw refused();
    return [{ ...first, host: HOST }, ...rest];
  }
  const port = Number(first);
  if (!Number.isInteger(port) || port < 0 || port > 65535) throw refused();
  if (typeof rest[0] === 'string') rest.shift();
  return [port, HOST, ...rest];
}

function localConnection(args) {
  // net.createConnection передаёт Socket.connect уже нормализованный массив.
  const input = Array.isArray(args[0]) ? args[0] : args;
  const first = input[0];
  const options = first && typeof first === 'object' ? first
    : { port: Number(first), host: typeof input[1] === 'string' ? input[1] : HOST };
  if (options.path || options.fd != null || !loopback(options.host || HOST)
    || !Number.isInteger(Number(options.port)) || Number(options.port) < 1
    || Number(options.port) > 65535 || Number(options.port) === 5037) throw refused();
}

function adbArgs(args) {
  if (!Array.isArray(args) || !args.every(arg => typeof arg === 'string' && !arg.includes('\0'))) throw refused();
  const [command, ...tail] = args;
  const global = (command === 'devices' && (tail.length === 0 || (tail.length === 1 && tail[0] === '-l')))
    || (['version', '--version', 'start-server', 'kill-server'].includes(command) && tail.length === 0);
  const scoped = command === '-s' && tail[0] === SERIAL && [
    'shell', 'exec-out', 'push', 'pull', 'forward', 'reverse',
    'get-state', 'get-serialno', 'get-devpath', 'wait-for-device', 'wait-for-disconnect',
  ].includes(tail[1]);
  if (!global && !scoped) throw refused();
  // Явный -H запрещает ADB автоматически поднимать отсутствующий daemon.
  // Только отдельный start-server получает право запуска и USB-фильтр.
  if (command === 'start-server') return ['-P', String(ADB_PORT), '--one-device', SERIAL, ...args];
  return ['-H', HOST, '-P', String(ADB_PORT), ...args];
}

function deviceOutput(args, stdout) {
  if (args[0] !== 'devices') return stdout;
  const text = String(stdout);
  const filtered = text.split(/\r?\n/).filter(line => line === ''
    || line.startsWith('List of devices attached') || line.startsWith(`${SERIAL}\t`)
    || line.startsWith(`${SERIAL} `)).join('\n');
  return Buffer.isBuffer(stdout) ? Buffer.from(filtered) : filtered;
}

function childEnvironment(environment) {
  return { ...environment,
    ADB_SERVER_SOCKET: `tcp:localhost:${ADB_PORT}`,
    ANDROID_ADB_SERVER_PORT: String(ADB_PORT),
    ADB_MDNS_AUTO_CONNECT: '0',
    ADB_MDNS: '0',
  };
}

module.exports = { HOST, HTTP_PORT, ADB_PORT, SERIAL, refused, loopback,
  localListenArgs, localConnection, adbArgs, deviceOutput, childEnvironment };
