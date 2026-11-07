// The direct network waveform contains one mean per 1 ms interval, not
// instantaneous samples. Draw each mean over its original interval.
export function stimulusDisplay(preview) {
  const current = preview?.stimulus_current_na;
  const fractions = preview?.stimulus_fraction;
  const times = preview?.stimulus_time_ms || preview?.time_ms;
  if (typeof current !== 'number' || !Number.isFinite(current)
      || !Array.isArray(fractions) || !Array.isArray(times) || !fractions.length
      || fractions.length !== times.length || !fractions.every(Number.isFinite)
      || !times.every((value, index) => Number.isFinite(value)
        && (index === 0 || value > times[index - 1]))) return null;
  if (!preview.networkOnly) return { current, times, fractions };
  const grid = preview.time_ms;
  if (!Array.isArray(grid) || grid.length !== fractions.length + 1
      || !grid.every((value, index) => Number.isFinite(value) && value === index)
      || !times.every((value, index) => value === index + .5)) return null;
  const expandedTimes = [], expandedFractions = [];
  fractions.forEach((value, index) => {
    expandedTimes.push(grid[index], grid[index + 1]);
    expandedFractions.push(value, value);
  });
  return { current, times: expandedTimes, fractions: expandedFractions };
}
