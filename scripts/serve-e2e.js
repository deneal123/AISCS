/*
 * Minimal static server for Playwright. Unlike http-server, it always falls
 * back to index.html for client-side routes and fails API calls immediately.
 */
const fs = require('fs');
const http = require('http');
const path = require('path');

const [buildArgument = '../build', portArgument = '3000'] = process.argv.slice(2);
const buildDir = path.resolve(process.cwd(), buildArgument);
const port = Number(portArgument);

if (!Number.isInteger(port) || port < 1 || port > 65535) {
  throw new Error(`Invalid port: ${portArgument}`);
}

const CONTENT_TYPES = {
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.webp': 'image/webp',
  '.woff2': 'font/woff2',
};

const safePath = (pathname) => {
  const decoded = decodeURIComponent(pathname);
  const candidate = path.resolve(buildDir, `.${decoded}`);
  return candidate.startsWith(`${buildDir}${path.sep}`) || candidate === buildDir ? candidate : null;
};

http.createServer((request, response) => {
  const requestUrl = new URL(request.url || '/', 'http://localhost');
  if (requestUrl.pathname.startsWith('/api/')) {
    response.writeHead(503, { 'Content-Type': 'application/json; charset=utf-8' });
    response.end(JSON.stringify({ detail: 'E2E static server has no API backend' }));
    return;
  }

  const candidate = safePath(requestUrl.pathname);
  const filePath = candidate && fs.existsSync(candidate) && fs.statSync(candidate).isFile()
    ? candidate
    : path.join(buildDir, 'index.html');
  const extension = path.extname(filePath).toLowerCase();
  response.writeHead(200, {
    'Cache-Control': 'no-store',
    'Content-Type': CONTENT_TYPES[extension] || 'application/octet-stream',
  });
  fs.createReadStream(filePath).on('error', () => {
    response.writeHead(500);
    response.end('Unable to read E2E build asset');
  }).pipe(response);
}).listen(port, '127.0.0.1', () => {
  process.stdout.write(`E2E static server listening on http://127.0.0.1:${port}\n`);
});
