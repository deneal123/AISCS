import { TextDecoder, TextEncoder } from 'util';
import { verifyFieldProxyEvents } from '../../../src/features/simulator/field/fieldProxyEvents';

beforeEach(() => {
  global.TextDecoder = TextDecoder;
  global.crypto = { subtle: { digest: jest.fn().mockResolvedValue(new Uint8Array(32).buffer) } };
});

function fixture() {
  const hash = '0'.repeat(64), ids = new BigUint64Array([1n, 2n]);
  const base = { node_ids: ids, description: { manifest_sha256: hash } };
  const buffer = new ArrayBuffer(32);
  new BigUint64Array(buffer, 0, 2).set(ids);
  new Int32Array(buffer, 16, 2).set([0, 1]);
  new Float32Array(buffer, 24, 2).set([1, 2]);
  const artifact = { name: 'network-events.bin', bytes: buffer.byteLength, sha256: hash };
  const field = { source_um: [1, 2, 3], return_um: [4, 5, 6], current_na: -300,
    conductivity_s_m: .3, clearance_um: 1 };
  const config = { graph_manifest_sha256: hash, seed: 1, gain: 3, waveform: [0, 1], ...field };
  const metadata = { graph_sha256: hash, event_sha256: hash, seed: 1, gain: 3, waveform: [0, 1],
    field: { field_audit: { configuration: field } },
    event_description: { manifest_sha256: hash, duration_ms: 2, binary: { byte_order: 'little', bytes: 32,
      arrays: { node_ids: { dtype: '<u8', offset: 0, count: 2, shape: [2] },
        spike_neurons: { dtype: '<i4', offset: 16, count: 2, shape: [2] },
        spike_times_ms: { dtype: '<f4', offset: 24, count: 2, shape: [2] } } } } };
  metadata.control_event_description = metadata.event_description;
  metadata.control_event_sha256 = hash;
  const encoded = new TextEncoder().encode(JSON.stringify(metadata));
  const meta = new ArrayBuffer(encoded.byteLength);
  new Uint8Array(meta).set(encoded);
  const metaArtifact = { name: 'metadata.json', bytes: meta.byteLength, sha256: hash };
  const controlArtifact = { name: 'network-control-events.bin', bytes: buffer.byteLength, sha256: hash };
  const run = { configuration: config, result: { manifest: { kind: 'experimental-field-proxy', files: [artifact, metaArtifact, controlArtifact] },
    preview: { duration_ms: 2, neurons: 2, spike_count: 2, active_neurons: 2,
      spikes_by_ms: [0, 1, 1], control_spikes_by_ms: [0, 1, 1], recording: null } } };
  return { base, buffer, artifact, meta, metaArtifact, run, control: buffer.slice(0), controlArtifact };
}

test('shows only verified network events and never claims electrode recording', async () => {
  const { base, buffer, artifact, meta, metaArtifact, run, control, controlArtifact } = fixture();
  const result = await verifyFieldProxyEvents(base, buffer, artifact, meta, metaArtifact, run, control, controlArtifact);
  expect([...result.spike_neurons]).toEqual([0, 1]);
  expect([...result.input_indices]).toEqual([]);
  expect([...result.control_spike_neurons]).toEqual([0, 1]);
  expect(result.description.interpretation).toContain('no physical recording');
});

test('rejects mismatched graph events and invented recordings', async () => {
  const first = fixture(); new BigUint64Array(first.buffer, 0, 2)[1] = 9n;
  await expect(verifyFieldProxyEvents(first.base, first.buffer, first.artifact, first.meta,
    first.metaArtifact, first.run, first.control, first.controlArtifact)).rejects.toThrow('field_proxy_nodes');
  const second = fixture(); second.run.result.preview.recording = [1, 2];
  await expect(verifyFieldProxyEvents(second.base, second.buffer, second.artifact, second.meta,
    second.metaArtifact, second.run, second.control, second.controlArtifact)).rejects.toThrow('field_proxy_identity');
  const third = fixture(); new BigUint64Array(third.control, 0, 2)[1] = 9n;
  await expect(verifyFieldProxyEvents(third.base, third.buffer, third.artifact, third.meta,
    third.metaArtifact, third.run, third.control, third.controlArtifact)).rejects.toThrow('field_proxy_control');
});
