// Exercise the existing browser worker and UI; no alternate simulation is injected.
import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { createRequire } from "node:module";
import { createHash } from "node:crypto";
import { gzipSync } from "node:zlib";

const run = path.resolve(process.argv[2]);
const work = path.resolve("research/.work/simulator-evaluation");
assert.equal(path.dirname(run), path.join(work, "SIM-009"));
const require = createRequire(path.join(work, "browser-tools/package.json"));
const { chromium } = require("playwright");
const dist = path.join(run, "source/frontend/dist");
const output = path.join(run, "exports/flybox");
fs.mkdirSync(output, {recursive:true});
const result = {scope:"real pinned FLYBOX Edge UI and its existing CPU WebWorker", errors:[], requestsFailed:[], trials:[]};
const mime = {".html":"text/html", ".js":"text/javascript", ".css":"text/css", ".json":"application/json", ".svg":"image/svg+xml", ".bin":"application/octet-stream"};
const server = http.createServer((req, res) => {
  const pathname = decodeURIComponent(new URL(req.url, "http://localhost").pathname);
  const file = path.resolve(dist, "." + pathname.replace(/\/$/, "/index.html"));
  if (!file.startsWith(dist + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
    res.writeHead(404); res.end(); return;
  }
  res.writeHead(200, {"Content-Type": mime[path.extname(file)] || "application/octet-stream"});
  fs.createReadStream(file).pipe(res);
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
result.url = `http://127.0.0.1:${server.address().port}`;
let context;
try {
  context = await chromium.launchPersistentContext(path.join(run,"browser-profile"), {
    executablePath:"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    headless:true, viewport:{width:1440,height:1000},
    args:["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--no-first-run"],
  });
  await context.addInitScript(() => {
    const NativeWorker = window.Worker;
    window.__probeFrames = 0;
    window.Worker = class extends NativeWorker {
      constructor(...args) {
        super(...args);
        window.__probeWorker = this;
        this.addEventListener("message", event => {
          if (event.data.type === "frame") {
            window.__probeFrame = event.data;
            window.__probeFrames++;
          }
        });
      }
    };
    let counter = 0;
    window.__probeRpc = (method, path, body) => new Promise((resolve,reject) => {
      const worker = window.__probeWorker;
      const id = "aspa-probe-" + ++counter;
      const timer = setTimeout(() => {worker.removeEventListener("message",listener);reject(new Error("RPC timeout " + path));},60000);
      const listener = event => {
        if (event.data.type !== "rpc_result" || event.data.id !== id) return;
        clearTimeout(timer); worker.removeEventListener("message",listener);
        if (event.data.ok) resolve(event.data.data); else reject(new Error(event.data.error));
      };
      worker.addEventListener("message",listener);
      worker.postMessage({type:"rpc",id,method,path,body});
    });
  });
  const page = await context.newPage();
  page.on("pageerror", e => result.errors.push(e.message));
  page.on("requestfailed", r => result.requestsFailed.push({url:r.url(),error:r.failure()?.errorText}));
  const started = performance.now();
  await page.goto(result.url, {waitUntil:"domcontentloaded"});
  await page.getByRole("button",{name:"OPEN THE SANDBOX",exact:true}).click();
  await page.waitForFunction(() => window.__probeFrame?.runtime?.status === "ready" || window.__probeFrame?.runtime?.status === "error",null,{timeout:180000});
  result.load_seconds = (performance.now() - started)/1000;
  const rpc = (method,path,body) => page.evaluate(args => window.__probeRpc(...args),[method,path,body]);
  let state = await rpc("GET","/api/state");
  assert.equal(state.runtime.status,"ready");
  assert.equal(state.runtime.neurons,166700);
  assert.equal(state.runtime.synapses,25088107);
  result.runtime = state.runtime;
  await rpc("POST","/api/simulation/pause");
  await page.screenshot({path:path.join(output,"browser-play.png")});
  await page.getByRole("button",{name:"LAB",exact:true}).click();
  await rpc("POST","/api/flies/prime/controller/lab");
  for (const seed of [1,2,3,1]) {
    await rpc("POST",`/api/world/randomize?seed=${seed}`);
    await rpc("POST","/api/simulation/reset");
    for (let i=0;i<20;i++) state = await rpc("POST","/api/simulation/step");
    const fly = state.flies.find(f=>f.id === "prime");
    assert.equal(fly.controller,"lab");
    assert([state.t,fly.x,fly.y,fly.heading,fly.energy,fly.fired_count].every(Number.isFinite));
    result.trials.push({seed,t:state.t,x:fly.x,y:fly.y,heading:fly.heading,energy:fly.energy,fired_count:fly.fired_count,motor:fly.motor});
  }
  result.repeat_seed_equal = JSON.stringify(result.trials[0]) === JSON.stringify(result.trials[3]);
  assert(result.repeat_seed_equal);
  const checkpoint = await rpc("POST","/api/time/checkpoint",{label:"acceptance"});
  const original = await rpc("GET","/api/state");
  const advanced = await rpc("POST","/api/simulation/step");
  assert(advanced.t > original.t);
  const restored = await rpc("POST","/api/time/rewind",{checkpoint_id:checkpoint.id});
  assert.equal(restored.t,original.t);
  result.rewind_time_equal = true;
  result.stimulate = await rpc("POST","/api/flies/prime/interventions",{type:"stimulate_population",target:"LC4",amount:1});
  await rpc("POST","/api/simulation/step");
  await rpc("POST","/api/flies/prime/interventions",{type:"silence_population",target:"LC4"});
  state = await rpc("POST","/api/simulation/step");
  let populations = await rpc("GET","/api/populations/prime");
  assert(populations.populations.find(p => p.name === "LC4").silenced);
  await rpc("POST","/api/flies/prime/interventions",{type:"restore_population",target:"LC4"});
  state = await rpc("POST","/api/simulation/step");
  populations = await rpc("GET","/api/populations/prime");
  assert(!populations.populations.find(p => p.name === "LC4").silenced);
  result.silence_restore_api = true;
  const worldObject = await rpc("POST","/api/world",{kind:"odor",x:0.45,y:0.4,intensity:0.7});
  assert(worldObject.id);
  result.add_world_object = worldObject;
  const soma = await rpc("GET","/api/brain/prime/sample");
  assert.equal(soma.kind,"anatomical");
  assert.equal(soma.mapped,140638);
  result.soma = {kind:soma.kind,mapped:soma.mapped,neurons:soma.neurons,points:soma.points.length};
  const exported = await rpc("GET","/api/experiments/export");
  const bytes = Buffer.from(JSON.stringify(exported));
  fs.writeFileSync(path.join(output,"experiment-export.json.gz"),gzipSync(bytes));
  result.export = {bytes:bytes.length,sha256:createHash("sha256").update(bytes).digest("hex"),runtime:exported.runtime};
  await page.screenshot({path:path.join(output,"browser-lab.png")});
  assert.equal(result.errors.length,0);
  result.optional_telemetry_failures = result.requestsFailed.filter(r => new URL(r.url).pathname.startsWith("/_vercel/"));
  const essentialFailures = result.requestsFailed.filter(r => !new URL(r.url).pathname.startsWith("/_vercel/"));
  assert.equal(essentialFailures.length,0);
  result.status = "passed";
} catch(e) {
  result.status = "failed"; result.failure = e.stack;
  if(context) await context.pages().at(-1)?.screenshot({path:path.join(output,"browser-failure.png")}).catch(()=>{});
  process.exitCode = 1;
} finally {
  if(context) await context.close();
  await new Promise(resolve=>server.close(resolve));
  fs.writeFileSync(path.join(output,"browser-result.json"),JSON.stringify(result,null,2)+"\n");
  console.log(JSON.stringify(result,null,2));
}
