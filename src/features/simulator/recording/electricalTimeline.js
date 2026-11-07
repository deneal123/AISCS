// Histogram only events already verified for the selected electrical run.
// A missing event stream stays missing, rather than becoming a zero response.
export function electricalSpikeHistogram(readout, durationMs) {
  const times = readout?.source?.spike_times_ms;
  if (!times || !Number.isInteger(durationMs) || durationMs < 1 || durationMs > 1000) return null;
  const bins = Array.from({ length: durationMs + 1 }, () => 0);
  for (const time of times) {
    if (!Number.isFinite(time) || time < 0 || time > durationMs) return null;
    bins[Math.floor(time)] += 1;
  }
  return bins;
}

// The scene and its histogram must describe the same network calculation.
export function sceneSpikeHistogram(sceneField, coupledHistogram, readout, durationMs, verifiedProxyHistogram = null) {
  if (sceneField?.result?.manifest?.kind === 'experimental-field-proxy') {
    return verifiedProxyHistogram;
  }
  return coupledHistogram ?? electricalSpikeHistogram(readout, durationMs);
}

// Object identity prevents a previous verification from approving a refreshed
// result or graph which happens to have the same persistent run ID.
export function verifiedHistogramForScene(state, runId, fieldRun, description) {
  if (!state || !fieldRun || state.runId !== runId || state.fieldRun !== fieldRun
      || state.description !== description) return null;
  return state.histogram;
}
