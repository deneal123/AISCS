import { createHash } from 'crypto';
import { TextDecoder, TextEncoder } from 'util';
import { verifyFieldProxyState } from '../../../src/features/simulator/field/fieldProxyState';

const hash = bytes => createHash('sha256').update(Buffer.from(bytes)).digest('hex');
const graphHash = 'a'.repeat(64), stateHash = 'b'.repeat(64), runHash = 'c'.repeat(64);
const graph = { node_ids: BigUint64Array.from([1n, 2n]), description: { manifest_sha256: graphHash } };
const field = { source_um: [1, 2, 3], return_um: [4, 5, 6], current_na: 10,
  conductivity_s_m: .3, clearance_um: 1 };

function fixture() {
  const response = new ArrayBuffer(76 + 2 * 8 + 2 * 3 * 4), view = new DataView(response);
  const bytes = new Uint8Array(response); bytes.set([70, 82, 83, 50]);
  view.setUint32(4, 2, true); view.setUint32(8, 3, true);
  bytes.fill(0xaa, 12, 44); bytes.fill(0xbb, 44, 76);
  view.setBigUint64(76, 1n, true); view.setBigUint64(84, 2n, true);
  view.setFloat32(100, -0.5, true);
  const file = { name: 'state-response.bin', bytes: response.byteLength, sha256: hash(response) };
  const config = { ...field, graph_manifest_sha256: graphHash, waveform: [0, 1], seed: 1, gain: 2 };
  const metadata = { graph_sha256: graphHash, waveform: config.waveform, seed: 1, gain: 2,
    field: { field_audit: { configuration: field } },
    state_delta: { status: 'limit_exceeded', configuration_sha256: stateHash, sampled_sha256: file.sha256 } };
  const encoded = new TextEncoder().encode(JSON.stringify(metadata));
  const metadataCopy = new Uint8Array(encoded.length); metadataCopy.set(encoded);
  const metadataBytes = metadataCopy.buffer;
  const metaFile = { name: 'metadata.json', bytes: metadataBytes.byteLength, sha256: hash(metadataBytes) };
  const run = { configuration: config, configuration_sha256: runHash,
    result: { manifest: { kind: 'experimental-field-proxy', configuration_sha256: runHash,
      files: [file, metaFile] } } };
  return { response, file, metadataBytes, metaFile, run };
}
beforeAll(() => { global.TextEncoder = TextEncoder; global.TextDecoder = TextDecoder;
  Object.defineProperty(global, 'crypto', { configurable: true, value: {
  subtle: { digest: async (_algorithm, bytes) => Uint8Array.from(createHash('sha256').update(Buffer.from(bytes)).digest()).buffer },
} }); });

test('authenticates and decodes whole-network sampled model-state difference', async () => {
  const { response, file, metadataBytes, metaFile, run } = fixture();
  const state = await verifyFieldProxyState(response, file, metadataBytes, metaFile, run, graph);
  expect(state.cells).toBe(2);
  expect(state.values[2]).toBe(-.5);
  expect(state.scope).toBe('network');
});

test('rejects tampering, wrong run and changed field configuration', async () => {
  const { response, file, metadataBytes, metaFile, run } = fixture();
  await expect(verifyFieldProxyState(response, file, metadataBytes, metaFile,
    { ...run, configuration_sha256: 'd'.repeat(64) }, graph)).rejects.toThrow('field_state_identity');
  await expect(verifyFieldProxyState(response, file, metadataBytes, metaFile,
    { ...run, configuration: { ...run.configuration, current_na: 11 } }, graph)).rejects.toThrow('field_state_provenance');
  new DataView(response).setFloat32(100, .5, true);
  await expect(verifyFieldProxyState(response, file, metadataBytes, metaFile, run, graph)).rejects.toThrow('field_state_checksum');
});
