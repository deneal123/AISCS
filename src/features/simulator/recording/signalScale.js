// A shared symmetric scale keeps both traces comparable, including sub-µV signals.
export function signalHalfRange(...traces) {
  let maximum = 0;
  traces.forEach(trace => (trace || []).forEach(value => {
    if (Number.isFinite(value)) maximum = Math.max(maximum, Math.abs(value));
  }));
  return maximum || 0.1;
}

export function signalAxisLabel(value) {
  if (value === 0) return '0';
  const magnitude = Math.abs(value);
  return magnitude < 0.01 || magnitude >= 1000 ? value.toExponential(1) : value.toPrecision(3);
}
