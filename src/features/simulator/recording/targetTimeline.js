// Endpoints may differ by solver roundoff; neither trace is resampled.
const sameTime = (a, b) => Number.isFinite(a) && Number.isFinite(b) && Math.abs(a - b) <= 1e-8;
const increasing = times => times.every((time, index) => Number.isFinite(time)
  && (index === 0 || time > times[index - 1]));

// A target replay extends exactly one saved source; it never replaces its network events.
export function targetTimeline(source, target) {
  const base = source?.result?.preview;
  const extra = target?.result?.preview;
  if (!source || !target || target.parent_run_id !== source.id || target.state !== 'completed'
      || !source.configuration?.graph_manifest_sha256
      || target.configuration?.graph_manifest_sha256 !== source.configuration.graph_manifest_sha256
      || !Array.isArray(base?.time_ms) || !Array.isArray(extra?.time_ms)
      || !Array.isArray(extra?.neural_uv) || extra.time_ms.length < 2
      || base.time_ms.length < 2
      || extra.neural_uv.length !== extra.time_ms.length
      || !sameTime(extra.time_ms[0], base.time_ms[0])
      || !sameTime(extra.time_ms.at(-1), base.time_ms.at(-1))
      || !increasing(base.time_ms) || !increasing(extra.time_ms)
      || extra.neural_uv.some(value => !Number.isFinite(value))
      || extra.source_cells !== source.configuration?.source_ids?.length
      || extra.target_id !== target.configuration?.target_id) return null;
  return extra;
}

// Keep the original stimulus time grid: preview extrema are selected independently.
export function stimulusSeries(source) {
  const times = source?.time_ms, values = source?.stimulus_fraction;
  if (!Array.isArray(times) || !Array.isArray(values) || times.length < 2 || times.length !== values.length
      || times.some((time, index) => !Number.isFinite(time) || (index > 0 && time <= times[index - 1]))
      || !values.every(Number.isFinite)) return null;
  return { time_ms: times, values };
}
