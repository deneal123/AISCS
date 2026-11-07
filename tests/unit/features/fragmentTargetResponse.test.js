import { createHash } from 'crypto';
import { verifyFragmentTargetResponse } from '../../../src/features/simulator/recording/fragmentTargetResponse';

const graphHash = 'a'.repeat(64), configHash = 'b'.repeat(64);
const graph = { node_ids: BigUint64Array.from([1n, 2n, 3n]), description: { manifest_sha256: graphHash } };
const testCrypto = { subtle: { digest: async (_algorithm, input) =>
  Uint8Array.from(createHash('sha256').update(Buffer.from(input)).digest()).buffer } };

function fixture() {
  const binary = new ArrayBuffer(76 + 2 * 8 + 2 * 4 * 4), view = new DataView(binary);
  new Uint8Array(binary).set([70, 82, 83, 49], 0);
  view.setUint32(4, 2, true); view.setUint32(8, 4, true);
  new Uint8Array(binary).fill(0xaa, 12, 44); new Uint8Array(binary).fill(0xbb, 44, 76);
  view.setBigUint64(76, 2n, true); view.setBigUint64(84, 3n, true);
  view.setFloat32(92 + 4 * 4, -0.5, true);
  const file = { name: 'fragment-response.bin', bytes: binary.byteLength,
    sha256: createHash('sha256').update(Buffer.from(binary)).digest('hex') };
  const run = { configuration_sha256: configHash,
    configuration: { graph_manifest_sha256: graphHash, source_ids: [1], simulation: { duration_ms: 3 } },
    result: { manifest: { kind: 'experimental-fragment-population', graph_sha256: graphHash,
      configuration_sha256: configHash, files: [file] } } };
  return { binary, file, run };
}

test('verifies identity and reconstructs paired target changes', async () => {
  global.crypto = testCrypto;
  const { binary, file, run } = fixture();
  const result = await verifyFragmentTargetResponse(binary, file, run, graph);
  expect(Array.from(result.indices)).toEqual([1, 2]);
  expect(result.values[4]).toBe(-0.5);
  expect(result.scope).toBe('direct-targets');
});

test('recognises full network response and rejects incomplete network coverage', async () => {
  global.crypto = testCrypto;
  const { binary, file, run } = fixture();
  new Uint8Array(binary)[3] = 50;
  const updatedFile = { ...file, sha256: createHash('sha256').update(Buffer.from(binary)).digest('hex') };
  const updatedRun = { ...run, result: { manifest: { ...run.result.manifest, files: [updatedFile] } } };
  expect((await verifyFragmentTargetResponse(binary, updatedFile, updatedRun, graph)).scope).toBe('network');
  const largerGraph = { ...graph, node_ids: BigUint64Array.from([1n, 2n, 3n, 4n]) };
  await expect(verifyFragmentTargetResponse(binary, updatedFile, updatedRun, largerGraph)).rejects.toThrow('response_coverage');
});

test('rejects mismatched metadata, tampering and source-cell targets', async () => {
  global.crypto = testCrypto;
  const { binary, file, run } = fixture();
  await expect(verifyFragmentTargetResponse(binary, file, { ...run, configuration_sha256: 'c'.repeat(64) }, graph)).rejects.toThrow();
  new DataView(binary).setBigUint64(76, 1n, true);
  await expect(verifyFragmentTargetResponse(binary, file, run, graph)).rejects.toThrow('response_checksum');
  const changed = { ...file, sha256: createHash('sha256').update(Buffer.from(binary)).digest('hex') };
  const updated = { ...run, result: { manifest: { ...run.result.manifest, files: [changed] } } };
  await expect(verifyFragmentTargetResponse(binary, changed, updated, graph)).rejects.toThrow('response_ids');
});

test('accepts a short recording covering more than 4096 targets', async () => {
  global.crypto = testCrypto;
  const cells = 5000, samples = 2, binary = new ArrayBuffer(76 + cells * 8 + cells * samples * 4);
  const view = new DataView(binary), bytes = new Uint8Array(binary);
  bytes.set([70, 82, 83, 49]); view.setUint32(4, cells, true); view.setUint32(8, samples, true);
  bytes.fill(0xaa, 12, 44); bytes.fill(0xbb, 44, 76);
  const nodes = BigUint64Array.from({ length: cells + 1 }, (_, index) => BigInt(index + 1));
  for (let index = 0; index < cells; index += 1) view.setBigUint64(76 + index * 8, nodes[index + 1], true);
  const file = { name: 'fragment-response.bin', bytes: binary.byteLength,
    sha256: createHash('sha256').update(Buffer.from(binary)).digest('hex') };
  const run = { configuration_sha256: configHash,
    configuration: { graph_manifest_sha256: graphHash, source_ids: [1], simulation: { duration_ms: 1 } },
    result: { manifest: { kind: 'experimental-fragment-population', graph_sha256: graphHash,
      configuration_sha256: configHash, files: [file] } } };
  const result = await verifyFragmentTargetResponse(binary, file, run,
    { node_ids: nodes, description: { manifest_sha256: graphHash } });
  expect(result.cells).toBe(5000);
});

test('decodes explicitly timed whole-network snapshots and rejects altered times', async () => {
  global.crypto = testCrypto;
  const cells = 4000, samples = 501, offset = 76 + samples * 4;
  const binary = new ArrayBuffer(offset + cells * 8 + cells * samples * 4);
  const view = new DataView(binary), bytes = new Uint8Array(binary);
  bytes.set([70, 82, 83, 51]); view.setUint32(4, cells, true); view.setUint32(8, samples, true);
  bytes.fill(0xaa, 12, 44); bytes.fill(0xbb, 44, 76);
  for (let i = 0; i < samples; i += 1) view.setUint32(76 + i * 4, i * 2, true);
  const nodes = BigUint64Array.from({ length: cells + 1 }, (_, i) => BigInt(i + 1));
  for (let i = 0; i < cells; i += 1) view.setBigUint64(offset + i * 8, nodes[i + 1], true);
  const makeFile = () => ({ name: 'fragment-response.bin', bytes: binary.byteLength,
    sha256: createHash('sha256').update(Buffer.from(binary)).digest('hex') });
  const makeRun = file => ({ configuration_sha256: configHash,
    configuration: { graph_manifest_sha256: graphHash, source_ids: [1], simulation: { duration_ms: 1000 } },
    result: { manifest: { kind: 'experimental-fragment-population', graph_sha256: graphHash,
      configuration_sha256: configHash, files: [file] } } });
  let file = makeFile();
  const response = await verifyFragmentTargetResponse(binary, file, makeRun(file),
    { node_ids: nodes, description: { manifest_sha256: graphHash } });
  expect(response.sampleTimes[500]).toBe(1000);
  view.setUint32(80, 3, true); file = makeFile();
  await expect(verifyFragmentTargetResponse(binary, file, makeRun(file),
    { node_ids: nodes, description: { manifest_sha256: graphHash } })).rejects.toThrow('response_times');
});
