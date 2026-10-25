// Real Edge/WebGL smoke, with a loopback-only temporary server and owned cleanup.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { createRequire } from 'node:module';

const run = path.resolve(process.argv[2]);
const work = path.resolve('research/.work/simulator-evaluation');
assert(run.startsWith(work + path.sep));
const require = createRequire(path.join(work, 'browser-tools/package.json'));
const { chromium } = require('playwright');
const dist = path.join(run, 'source/dist');
const mime = { '.html':'text/html', '.js':'text/javascript', '.css':'text/css', '.json':'application/json', '.wasm':'application/wasm' };
const server = http.createServer((req, res) => {
  const file = path.resolve(dist, '.' + new URL(req.url, 'http://localhost').pathname.replace(/\/$/, '/index.html'));
  if (!file.startsWith(dist + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { 'Content-Type':mime[path.extname(file)] || 'application/octet-stream', 'Cache-Control':'no-store' });
  fs.createReadStream(file).pipe(res);
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const url = `http://127.0.0.1:${server.address().port}`;
let context;
const result = { url, errors:[], failedResources:[], scope:'real Edge software WebGL, pinned local corpus' };
try {
  context = await chromium.launchPersistentContext(path.join(run, 'browser-profile'), {
    executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless:true,
    args:['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--renderer-process-limit=1'], viewport:{width:1280,height:800},
  });
  const page = context.pages()[0];
  page.setDefaultTimeout(60000);
  page.on('pageerror', e => result.errors.push(String(e)));
  page.on('response', r => { if (r.status() >= 400 && !r.url().endsWith('/favicon.ico')) result.failedResources.push(r.url()); });
  await page.goto(url);
  await page.locator('#fly-name').fill('SIM-003');
  await page.locator('#name-form button').click();
  await page.waitForFunction(() => window.__flyReady || window.__flyError, null, { timeout:90000 });
  assert.equal(await page.evaluate(() => window.__flyError), undefined);
  if (await page.locator('#about').isVisible()) await page.locator('#about button[aria-label="Close about"]').click();
  result.before = await page.evaluate(() => ({...window.fly.dbg(), neurons:window.fly.brain.N, edges:window.fly.brain.colidx.length, spikes:window.fly.brain.totalSpikes}));
  await page.waitForFunction(ms => window.fly.brain.ms > ms + 10, result.before.brainMs);
  await page.locator('#b_pause').click();
  result.paused = await page.evaluate(() => window.fly.dbg());
  assert(result.paused.paused);
  await page.locator('#b_sugar').click();
  assert.equal(await page.evaluate(() => window.fly.brain.sugar), 0);
  await page.locator('#b_sugar').click();
  assert.equal(await page.evaluate(() => window.fly.brain.sugar), 1);
  await page.locator('#b_home').click();
  await page.screenshot({path:path.join(run,'browser-scene.png')});
  await page.locator('#b_inspect').click();
  assert(await page.locator('#inspect').isVisible());
  result.inspector = await page.locator('#hud').innerText();
  result.finite = await page.evaluate(() => Array.from(window.fly.brain.v).every(Number.isFinite) && Array.from(window.fly.data.qpos).every(Number.isFinite));
  assert(result.finite);
  await page.screenshot({path:path.join(run,'browser-inspector.png')});
  assert.equal(result.errors.length,0);
  assert.equal(result.failedResources.length,0);
  result.status='passed';
} catch (e) {
  result.status='failed'; result.error=String(e); process.exitCode=1;
} finally {
  if (context) await context.close();
  await new Promise(resolve => server.close(resolve));
  const receipt = path.join(run,'browser-result.json');
  if (fs.existsSync(receipt)) fs.renameSync(receipt,path.join(run,`browser-result-${Date.now()}.json`));
  fs.writeFileSync(receipt,JSON.stringify(result,null,2)+'\n');
  console.log(JSON.stringify(result,null,2));
}
