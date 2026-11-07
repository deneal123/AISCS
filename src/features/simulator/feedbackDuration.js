// Integer network ticks must contain the full configured pulse train and align
// with the physical solver's sampling grid. This is not an electrode safety check.
export function validFeedbackDuration(simulation, value) {
  if (String(value).trim() === '') return false;
  const duration = Number(value), dt = simulation?.dt_ms;
  const start = simulation?.pulse_start_ms, end = simulation?.pulse_end_ms;
  const rise = simulation?.rise_time_ms, gap = simulation?.interphase_gap_ms;
  const shape = simulation?.pulse_shape, count = simulation?.pulse_count ?? 1;
  const interval = simulation?.pulse_interval_ms;
  if (!Number.isInteger(duration) || duration < 1 || duration > 1000
      || ![dt, start, end, rise, gap].every(Number.isFinite) || dt <= 0
      || !(0 < start && start < end) || rise < 0 || 2 * rise > end - start
      || gap < 0 || !['monophasic', 'biphasic'].includes(shape)
      || (shape === 'monophasic' && gap !== 0)
      || !Number.isInteger(count) || count < 1 || count > 1000) return false;
  const extent = (end - start) * (shape === 'biphasic' ? 2 : 1) + (shape === 'biphasic' ? gap : 0);
  if (count === 1 ? interval != null : !Number.isFinite(interval) || interval <= extent) return false;
  const finish = start + (count - 1) * (interval || 0) + extent;
  return finish < duration && Math.abs(Math.round(duration / dt) * dt - duration) <= 1e-9;
}
