// Decode the verified, uncalibrated whole-network proxy without assigning
// physiological meaning or fabricating an extracellular recording.
export async function verifyFieldProxyEvents(base, buffer, artifact, metadataBuffer, metadataArtifact, run,
  controlBuffer, controlArtifact) {
  const files = run?.result?.manifest?.files;
  for (const file of [artifact, metadataArtifact, controlArtifact]) {
    const entry = Array.isArray(files) && files.find(item => item.name === file?.name);
    if (!entry || entry.bytes !== file?.bytes || entry.sha256 !== file?.sha256) throw new Error('field_proxy_manifest');
  }
  async function verify(bytes, file) {
    if (!(bytes instanceof ArrayBuffer) || bytes.byteLength !== file?.bytes
        || !/^[a-f0-9]{64}$/.test(file?.sha256 || '')) throw new Error('field_proxy_size');
    const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))]
      .map(value => value.toString(16).padStart(2, '0')).join('');
    if (digest !== file.sha256) throw new Error('field_proxy_checksum');
  }
  await Promise.all([verify(buffer, artifact), verify(metadataBuffer, metadataArtifact),
    verify(controlBuffer, controlArtifact)]);
  const metadata = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(metadataBuffer));
  const config = run?.configuration, preview = run?.result?.preview;
  const desc = metadata.event_description, layout = desc?.binary?.arrays;
  const n = base?.node_ids?.length, duration = config?.waveform?.length;
  const fieldConfig = metadata.field?.field_audit?.configuration;
  const fieldKeys = ['source_um', 'return_um', 'current_na', 'conductivity_s_m', 'clearance_um'];
  if (!n || run?.result?.manifest?.kind !== 'experimental-field-proxy'
      || metadata.graph_sha256 !== base.description?.manifest_sha256
      || config?.graph_manifest_sha256 !== metadata.graph_sha256
      || desc?.manifest_sha256 !== metadata.graph_sha256
      || metadata.event_sha256 !== artifact.sha256
      || metadata.seed !== config.seed || metadata.gain !== config.gain
      || JSON.stringify(metadata.waveform) !== JSON.stringify(config.waveform)
      || !fieldConfig || fieldKeys.some(key => config[key] === undefined
        || JSON.stringify(fieldConfig[key]) !== JSON.stringify(config[key]))
      || !Number.isInteger(duration) || duration < 1 || duration > 1000
      || desc.duration_ms !== duration || preview?.duration_ms !== duration
      || preview?.recording !== null || preview?.neurons !== n
      || desc.binary?.byte_order !== 'little' || desc.binary?.bytes !== buffer.byteLength) {
    throw new Error('field_proxy_identity');
  }
  const missing = metadata.field?.excluded_from_direct_field;
  const contacts = metadata.field?.excluded_contact_intersections;
  if (!Array.isArray(missing) || !Array.isArray(contacts)
      || preview.direct_field_exclusions !== missing.length || preview.contact_exclusions !== contacts.length
      || missing.length + contacts.length > n) throw new Error('field_proxy_exclusions');
  const excluded = new Set();
  for (const id of [...missing, ...contacts]) {
    if (typeof id !== 'string' || !/^[1-9]\d{0,18}$/.test(id) || BigInt(id) >= 2n ** 63n
        || excluded.has(id)) throw new Error('field_proxy_exclusions');
    excluded.add(id);
  }
  if (excluded.size) for (const id of base.node_ids) {
    excluded.delete(id.toString());
    if (!excluded.size) break;
  }
  if (excluded.size) throw new Error('field_proxy_exclusions');
  let offset = 0;
  for (const [key, dtype, width] of [['node_ids', '<u8', 8], ['spike_neurons', '<i4', 4], ['spike_times_ms', '<f4', 4]]) {
    const item = layout?.[key];
    if (!item || item.dtype !== dtype || item.offset !== offset || !Number.isSafeInteger(item.count)
        || item.count < 0 || !Array.isArray(item.shape) || item.shape.length !== 1 || item.shape[0] !== item.count) throw new Error('field_proxy_layout');
    offset += item.count * width;
  }
  if (offset !== buffer.byteLength || layout.node_ids.count !== n
      || layout.spike_neurons.count !== layout.spike_times_ms.count
      || layout.spike_neurons.count !== preview.spike_count) throw new Error('field_proxy_layout');
  const ids = new BigUint64Array(buffer, layout.node_ids.offset, n);
  if (!ids.every((id, i) => id === base.node_ids[i])) throw new Error('field_proxy_nodes');
  const indices = new Int32Array(buffer, layout.spike_neurons.offset, layout.spike_neurons.count);
  const times = new Float32Array(buffer, layout.spike_times_ms.offset, layout.spike_times_ms.count);
  const counts = new Int32Array(n), perTick = new Uint32Array(duration + 1);
  indices.forEach((index, i) => {
    if (index < 0 || index >= n || !Number.isInteger(times[i]) || times[i] <= 0
        || times[i] > duration || (i && times[i] < times[i - 1])) throw new Error('field_proxy_events');
    counts[index] += 1; perTick[times[i]] += 1;
  });
  if (!Array.isArray(preview.spikes_by_ms) || preview.spikes_by_ms.length !== perTick.length
      || !perTick.every((value, i) => value === preview.spikes_by_ms[i])
      || counts.reduce((sum, value) => sum + Number(value > 0), 0) !== preview.active_neurons) throw new Error('field_proxy_preview');
  const controlDesc = metadata.control_event_description, controlLayout = controlDesc?.binary?.arrays;
  if (metadata.control_event_sha256 !== controlArtifact.sha256
      || controlDesc?.manifest_sha256 !== metadata.graph_sha256 || controlDesc?.duration_ms !== duration
      || controlDesc?.binary?.byte_order !== 'little' || controlDesc?.binary?.bytes !== controlBuffer.byteLength) throw new Error('field_proxy_control');
  let controlOffset = 0;
  for (const [key, dtype, width] of [['node_ids', '<u8', 8], ['spike_neurons', '<i4', 4], ['spike_times_ms', '<f4', 4]]) {
    const item = controlLayout?.[key];
    if (!item || item.dtype !== dtype || item.offset !== controlOffset || !Number.isSafeInteger(item.count)
        || item.count < 0 || !Array.isArray(item.shape) || item.shape.length !== 1 || item.shape[0] !== item.count) throw new Error('field_proxy_control');
    controlOffset += item.count * width;
  }
  if (controlOffset !== controlBuffer.byteLength || controlLayout.node_ids.count !== n
      || controlLayout.spike_neurons.count !== controlLayout.spike_times_ms.count) throw new Error('field_proxy_control');
  const controlIds = new BigUint64Array(controlBuffer, controlLayout.node_ids.offset, n);
  if (!controlIds.every((id, i) => id === base.node_ids[i])) throw new Error('field_proxy_control');
  const controlIndices = new Int32Array(controlBuffer, controlLayout.spike_neurons.offset, controlLayout.spike_neurons.count);
  const controlTimes = new Float32Array(controlBuffer, controlLayout.spike_times_ms.offset, controlLayout.spike_times_ms.count);
  const controlPerTick = new Uint32Array(duration + 1);
  controlIndices.forEach((index, i) => {
    if (index < 0 || index >= n || !Number.isInteger(controlTimes[i]) || controlTimes[i] <= 0
        || controlTimes[i] > duration || (i && controlTimes[i] < controlTimes[i - 1])) throw new Error('field_proxy_control');
    controlPerTick[controlTimes[i]] += 1;
  });
  if (!Array.isArray(preview.control_spikes_by_ms) || preview.control_spikes_by_ms.length !== controlPerTick.length
      || !controlPerTick.every((value, i) => value === preview.control_spikes_by_ms[i])) throw new Error('field_proxy_control');
  return { ...base, spike_neurons: indices, spike_times_ms: times, counts, input_indices: new Int32Array(),
    control_spike_neurons: controlIndices, control_spike_times_ms: controlTimes,
    description: { ...base.description, duration_ms: duration, spikes: indices.length,
      input_neurons: 0, active_neurons: preview.active_neurons, stimulus_region: 'electrical',
      interpretation: 'uncalibrated whole-network model events; no physical recording' } };
}
