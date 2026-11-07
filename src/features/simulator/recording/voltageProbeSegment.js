// Show only a verified SWC segment; color is a display of voltage difference, not propagation.
export function voltageProbeSegment(morphology, preview, selectedNodeId, timeMs) {
  const probe = preview?.voltage_probe, times = preview?.time_ms;
  const baseline = preview?.probe_baseline_mv, active = preview?.probe_active_mv;
  if (!morphology || morphology.sha256 !== preview?.probe_morphology_sha256
      || String(preview?.target_id) !== String(selectedNodeId)
      || !probe || !Number.isInteger(probe.segment_index) || !Number.isInteger(probe.segments_per_edge)
      || probe.segments_per_edge < 1 || probe.segment_index < 0
      || probe.segment_index >= probe.segments_per_edge
      || !Array.isArray(times) || times.length < 2 || !Array.isArray(baseline) || !Array.isArray(active)
      || times.length !== baseline.length || times.length !== active.length || !Number.isFinite(timeMs)) return null;
  const edge = morphology.segmentsByChild?.get(probe.child_node_id);
  if (!edge || !Array.isArray(edge.start) || !Array.isArray(edge.end)
      || edge.start.length !== 3 || edge.end.length !== 3
      || !edge.start.every(Number.isFinite) || !edge.end.every(Number.isFinite)) return null;
  let left = 0, right = times.length - 1;
  while (left < right) {
    const mid = Math.ceil((left + right) / 2);
    if (times[mid] <= timeMs + 1e-8) left = mid; else right = mid - 1;
  }
  if (timeMs < times[0] - 1e-8 || timeMs > times.at(-1) + 1e-8 || !Number.isFinite(active[left])
      || !Number.isFinite(baseline[left])) return null;
  const a = probe.segment_index / probe.segments_per_edge, b = (probe.segment_index + 1) / probe.segments_per_edge;
  const point = fraction => edge.start.map((value, index) => value + (edge.end[index] - value) * fraction);
  return { positions: [...point(a), ...point(b)], deltaMv: active[left] - baseline[left], sampleTimeMs: times[left] };
}
