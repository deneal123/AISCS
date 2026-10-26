// Observe the unmodified author pages in an isolated installed Edge profile.
import { createRequire } from "node:module";
import { writeFile, mkdir, readFile } from "node:fs/promises";
import path from "node:path";
import assert from "node:assert/strict";

const source = path.resolve(process.env.ASPA_SOUP_SOURCE);
const output = path.resolve(process.env.ASPA_SOUP_OUTPUT);
const require = createRequire(path.join(source, "web", "package.json"));
const { chromium } = require("playwright");
await mkdir(output, { recursive: true });
const context = await chromium.launchPersistentContext(process.env.ASPA_SOUP_PROFILE, {
  executablePath: process.env.SOUP_CONNECTOME_E2E_EXECUTABLE,
  headless: true,
  viewport: { width: 1440, height: 1080 },
  args: ["--enable-unsafe-webgpu", "--enable-features=WebGPU", "--use-angle=d3d11"],
});
try {
  for (const [name, route, timeout] of [
    ["fixture", "/test/e2e.html", 60_000],
    ["fullscale", "/web/test/fullscale.html", 600_000],
  ]) {
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(String(error)));
    const started = performance.now();
    const record = { scope: `unmodified author ${name} browser page`, errors };
    try {
      await page.goto(process.env.ASPA_SOUP_BASE_URL + route);
      await page.waitForFunction(
        () => /^(PASS|FAIL|ERROR)/.test(document.title), null, { timeout },
      );
      record.title = await page.title();
      record.result = JSON.parse(await page.locator("#result").textContent());
      record.status = record.result.status === "PASS" ? "passed" : "failed";
      if (name === "fixture" && record.status === "passed") {
        assert.deepEqual(record.result.webgpu, record.result.wasm);
        assert.deepEqual(record.result.webgpu, record.result.expected);
      }
      if (name === "fullscale" && record.status === "passed") {
        const manifest = JSON.parse(await readFile(path.join(source, "..", "cache", "male-cns-v1.0-annotated.scx", "manifest.json"), "utf8"));
        assert.equal(record.result.nNeurons, manifest.n_neurons);
        assert.equal(record.result.nEdges, manifest.n_edges);
        assert.equal(record.result.blocks, manifest.blocks.length);
      }
      const adapter = await page.evaluate(async () => {
        const a = await navigator.gpu?.requestAdapter();
        return a?.info ? { vendor: a.info.vendor, architecture: a.info.architecture,
          device: a.info.device, description: a.info.description } : null;
      });
      record.adapter = adapter;
    } catch (error) {
      record.status = "failed";
      record.error = String(error);
      record.title = await page.title();
      record.visible_result = await page.locator("#result").textContent().catch(() => null);
    } finally {
      record.seconds = (performance.now() - started) / 1000;
      record.browser = context.browser()?.version();
      await page.screenshot({ path: path.join(output, `browser-${name}.png`), fullPage: true });
      await writeFile(path.join(output, `browser-${name}.json`), JSON.stringify(record, null, 2) + "\n");
      await page.close();
    }
    console.log(name, record.status);
  }
  const cpu = JSON.parse(await readFile(path.join(source, "..", "exports", "full-male-cns", "active-stress.json"), "utf8"));
  const page = await context.newPage();
  try {
    await page.goto(process.env.ASPA_SOUP_BASE_URL + "/web/test/fullscale.html");
    await page.waitForFunction(() => /^(PASS|FAIL|ERROR)/.test(document.title), null, { timeout: 600_000 });
    const result = await page.evaluate(async (golden) => {
      const { openArtifact, requestWebGPUDevice, runStreamed } = await import("/web/src/index.js");
      const artifact = await openArtifact("/artifacts/male-cns-v1.0-annotated.scx/");
      const device = await requestWebGPUDevice();
      const config = { threshold: 1, reset: 0, decay_shifts: [31], refractory_steps: 0 };
      const initial = Array(artifact.manifest.n_neurons).fill(0);
      initial[0] = 30000;
      const started = performance.now();
      const values = await runStreamed({ device, artifact, config, timesteps: 2, initialPotentials: initial });
      const wallSeconds = (performance.now() - started) / 1000;
      const spikes = Uint8Array.from(values.spikes.flat(), Number);
      const potential = new Uint8Array(new Int32Array(values.finalPotentials).buffer);
      const hash = async (bytes) => Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)), (b) => b.toString(16).padStart(2, "0")).join("");
      const spikesHash = await hash(spikes);
      const potentialHash = await hash(potential);
      const counts = values.spikes.map((step) => step.reduce((sum, v) => sum + Number(v), 0));
      const passed = spikesHash === golden.spikes_sha256 && potentialHash === golden.potential_sha256;
      const encode = (bytes) => {
        let result = "";
        for (let i = 0; i < bytes.length; i += 8192) result += String.fromCharCode(...bytes.subarray(i, i + 8192));
        return btoa(result);
      };
      return { status: passed ? "passed" : "failed", scope: "additional API active integer stress; not a biological model",
        nNeurons: artifact.manifest.n_neurons, nEdges: artifact.manifest.n_edges, config, wallSeconds,
        spikesPerStep: counts, spikes_sha256: spikesHash, potential_sha256: potentialHash,
        cpu_exact_parity: passed, spikes_b64: encode(spikes), potential_b64: encode(potential) };
    }, cpu.trials[0]);
    await writeFile(path.join(output, "active-webgpu-spikes-u8.bin"), Buffer.from(result.spikes_b64, "base64"));
    await writeFile(path.join(output, "active-webgpu-potential-int32le.bin"), Buffer.from(result.potential_b64, "base64"));
    delete result.spikes_b64;
    delete result.potential_b64;
    await page.evaluate((record) => {
      document.querySelector(".eyebrow").textContent = "additional API validation / active full graph";
      document.querySelector(".lede").textContent = "Two active fixed-point steps on the registered MaleCNS graph; exact comparison with Python CPU. No biological calibration.";
      document.querySelector("#result").textContent = JSON.stringify(record, null, 2);
      document.title = record.status.toUpperCase() + " active CPU / WebGPU parity";
    }, result);
    await page.screenshot({ path: path.join(output, "browser-active.png"), fullPage: true });
    await writeFile(path.join(output, "browser-active.json"), JSON.stringify(result, null, 2) + "\n");
    console.log("active", result.status);
  } catch (error) {
    await writeFile(path.join(output, "browser-active.json"), JSON.stringify({ status: "failed", error: String(error), scope: "additional API active stress" }, null, 2) + "\n");
  } finally {
    await page.close();
  }
} finally {
  await context.close();
}
const results = await Promise.all(["fixture", "fullscale", "active"].map(async (name) =>
  JSON.parse(await readFile(path.join(output, `browser-${name}.json`), "utf8"))));
process.exitCode = results.every((r) => r.status === "passed") ? 0 : 1;
