export function playableTimeline(preview) {
  const times = preview?.time_ms;
  const signal = preview?.signal_uv;
  return Array.isArray(times) && times.length > 1
    && (preview?.networkOnly === true || (Array.isArray(signal)
      && signal.length === times.length && signal.every(Number.isFinite)))
    && times.every((time, index) => Number.isFinite(time) && time >= 0
      && (index === 0 || time > times[index - 1])) && times[times.length - 1] > 0;
}
