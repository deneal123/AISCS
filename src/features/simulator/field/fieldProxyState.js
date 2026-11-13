import { decodeTargetResponse } from '../recording/fragmentTargetResponse';

const sha = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const hex = bytes => Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');

// Saved samples are model-state differences, not electrode potentials or spikes.
export async function verifyFieldProxyState(buffer, artifact, metadataBuffer, metadataArtifact, run, graph) {
  const manifest = run?.result?.manifest, config = run?.configuration;
  const graphHash = config?.graph_manifest_sha256, runHash = run?.configuration_sha256;
  if (manifest?.kind !== 'experimental-field-proxy' || !sha(runHash)
      || manifest.configuration_sha256 !== runHash || !sha(graphHash)
      || graph?.description?.manifest_sha256 !== graphHash
      || !Array.isArray(config?.waveform) || !config.waveform.length || config.waveform.length > 1000)
    throw new Error('field_state_identity');
  for (const [data, file, name, maximum] of [[buffer, artifact, 'state-response.bin', 24000000],
    [metadataBuffer, metadataArtifact, 'metadata.json', 8388608]]) {
    const entry = manifest.files?.find(item => item.name === name);
    if (!(data instanceof ArrayBuffer) || data.byteLength > maximum || data.byteLength !== file?.bytes
        || file.name !== name || !sha(file.sha256) || entry?.bytes !== file.bytes || entry?.sha256 !== file.sha256)
      throw new Error('field_state_identity');
    if (hex(new Uint8Array(await crypto.subtle.digest('SHA-256', data))) !== file.sha256)
      throw new Error('field_state_checksum');
  }
  const metadata = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(metadataBuffer));
  const field = metadata.field?.field_audit?.configuration;
  const keys = ['source_um', 'return_um', 'current_na', 'conductivity_s_m', 'clearance_um'];
  if (metadata.graph_sha256 !== graphHash || metadata.seed !== config.seed || metadata.gain !== config.gain
      || JSON.stringify(metadata.waveform) !== JSON.stringify(config.waveform)
      || !field || keys.some(key => config[key] === undefined || JSON.stringify(config[key]) !== JSON.stringify(field[key]))
      || !['recorded', 'limit_exceeded'].includes(metadata.state_delta?.status)
      || metadata.state_delta.sampled_sha256 !== artifact.sha256 || !sha(metadata.state_delta.configuration_sha256))
    throw new Error('field_state_provenance');
  const state = decodeTargetResponse(buffer, graph, { graphHash, configHash: metadata.state_delta.configuration_sha256,
    duration: config.waveform.length, sources: [] });
  if (state.scope !== 'network' || state.cells !== graph.node_ids.length) throw new Error('field_state_coverage');
  return state;
}
