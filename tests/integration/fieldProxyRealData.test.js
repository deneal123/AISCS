// Opt-in offline integration check: ASPA_FIELD_FIXTURE points to a generated
// field-proxy output and graph-ids-test.bin. It does not start a service.
import { webcrypto } from 'crypto';
import fs from 'fs';
import path from 'path';
import { TextDecoder } from 'util';
import { verifyFieldProxyEvents } from '../../src/features/simulator/field/fieldProxyEvents';
import { createConnectomeLayer } from '../../src/features/simulator/connectome/connectomeLayer';
import { verifyFieldProxyState } from '../../src/features/simulator/field/fieldProxyState';
import { createStateContrastLayer } from '../../src/features/simulator/stateContrastLayer';

const fixture = process.env.ASPA_FIELD_FIXTURE;
const itWithFixture = fixture ? test : test.skip;
jest.setTimeout(30000);

itWithFixture('verifies exported whole-graph events and exclusions against independent graph IDs', async () => {
  global.TextDecoder = TextDecoder;
  Object.defineProperty(global, 'crypto', { configurable: true, value: webcrypto });
  const read = name => {
    const bytes = fs.readFileSync(path.join(fixture, name));
    const array = new Uint8Array(bytes.byteLength);
    array.set(bytes);
    return array.buffer;
  };
  const sha = async bytes => Buffer.from(await webcrypto.subtle.digest('SHA-256', bytes)).toString('hex');
  const artifact = async (name, bytes) => ({ name, bytes: bytes.byteLength, sha256: await sha(bytes) });
  const [events, control, metaBytes, graphBytes, previewBytes, manifestBytes, stateBytes] = [
    'network-events.bin', 'network-control-events.bin', 'metadata.json',
    'graph-ids-test.bin', 'field-proxy-preview.json', 'manifest.json', 'state-response.bin',
  ].map(read);
  const metadata = JSON.parse(new TextDecoder().decode(metaBytes));
  const preview = JSON.parse(new TextDecoder().decode(previewBytes));
  const manifest = JSON.parse(new TextDecoder().decode(manifestBytes));
  const [eventFile, controlFile, metaFile] = await Promise.all([
    artifact('network-events.bin', events), artifact('network-control-events.bin', control),
    artifact('metadata.json', metaBytes),
  ]);
  const config = { ...metadata.field.field_audit.configuration, graph_manifest_sha256: metadata.graph_sha256,
    seed: metadata.seed, gain: metadata.gain, waveform: metadata.waveform };
  expect(await artifact('field-proxy-preview.json', previewBytes))
    .toEqual(expect.objectContaining(manifest.files.find(file => file.name === 'field-proxy-preview.json')));
  const run = { configuration: config, configuration_sha256: manifest.configuration_sha256,
    result: { manifest, preview } };
  const base = { node_ids: new BigUint64Array(graphBytes),
    description: { manifest_sha256: metadata.graph_sha256 } };
  expect(base.node_ids.length).toBe(166700);
  expect(preview.recording).toBeNull();
  expect(Number.isInteger(preview.direct_field_exclusions)).toBe(true);
  expect(Number.isInteger(preview.contact_exclusions)).toBe(true);
  expect(preview.direct_field_exclusions).toBeGreaterThanOrEqual(0);
  expect(preview.contact_exclusions).toBeGreaterThanOrEqual(0);
  const result = await verifyFieldProxyEvents(base, events, eventFile, metaBytes, metaFile,
    run, control, controlFile);
  expect(result.spike_neurons.length).toBe(preview.spike_count);
  expect(result.spike_neurons.length).toBeGreaterThan(0);
  expect(result.description.interpretation).toContain('no physical recording');
  // Synthetic positions deliberately exercise only the event-clock and GPU-buffer
  // update path; no anatomical placement or actual browser rendering is claimed.
  const sceneData = { ...result, positions_mm: new Float32Array(base.node_ids.length * 3),
    edge_pre: new Uint32Array(), edge_post: new Uint32Array(), edge_sign: new Int8Array(),
    description: { ...result.description, synaptic_delay_ms: 2, scene: { routes_mm: {} } } };
  const layer = createConnectomeLayer(sceneData);
  try {
    const firstIndex = result.spike_neurons[0], firstTime = result.spike_times_ms[0];
    const id = result.node_ids[firstIndex].toString();
    expect(layer.update(0, true, true).delivered).toBe(0);
    const firstFrame = layer.update(firstTime, true, true);
    expect(firstFrame.delivered)
      .toBe(preview.spikes_by_ms.slice(0, firstTime + 1).reduce((a, b) => a + b, 0));
    expect(firstFrame.active).toBeGreaterThan(0);
    expect(layer.lastSpikeTime(id)).toBe(firstTime);
    expect(layer.group.children[0].geometry.attributes.firedAt.array[firstIndex]).toBe(firstTime);
    const lastEvent = new Float32Array(base.node_ids.length).fill(-1000);
    let cursor = 0;
    for (let time = 1; time <= preview.duration_ms; time += 1) {
      while (cursor < result.spike_times_ms.length && result.spike_times_ms[cursor] <= time) {
        lastEvent[result.spike_neurons[cursor]] = result.spike_times_ms[cursor];
        cursor += 1;
      }
      const expectedActive = lastEvent.reduce((count, at) => count + Number(time - at >= 0 && time - at < 6), 0);
      const frame = layer.update(time, true, true);
      expect(frame.delivered).toBe(cursor);
      expect(frame.active).toBe(expectedActive);
    }
    expect(cursor).toBe(preview.spike_count);
    for (let i = 0; i < cursor; i += 1) {
      const index = result.spike_neurons[i];
      expect(layer.group.children[0].geometry.attributes.firedAt.array[index]).toBe(lastEvent[index]);
    }
    expect(layer.update(0, true, true).delivered).toBe(0);
    expect(layer.lastSpikeTime(id)).toBeNull();
    expect(layer.group.children[0].geometry.attributes.firedAt.array[firstIndex]).toBe(-1000);
  } finally {
    layer.dispose();
  }
  const stateFile = await artifact('state-response.bin', stateBytes);
  const state = await verifyFieldProxyState(stateBytes, stateFile, metaBytes, metaFile, run, base);
  expect(state.cells).toBe(166700);
  expect(state.sampleTimes[0]).toBe(0);
  expect(state.sampleTimes[state.sampleTimes.length - 1]).toBe(preview.duration_ms);
  const contrast = createStateContrastLayer({ ...sceneData,
    coordinate_kind: new Uint8Array(base.node_ids.length).fill(1) }, state);
  try {
    expect(contrast.update(0).active).toBe(0);
    const at30 = contrast.update(30);
    expect(at30.sample).toBe(30);
    expect(at30.active).toBeGreaterThan(0);
    expect(contrast.update(0).active).toBe(0);
  } finally { contrast.dispose(); }
  run.result.preview.contact_exclusions += 1;
  await expect(verifyFieldProxyEvents(base, events, eventFile, metaBytes, metaFile,
    run, control, controlFile)).rejects.toThrow('field_proxy_exclusions');
});
