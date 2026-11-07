// Whole-cell highlighting denotes a recorded event, not measured conduction.
export function neighborIsActive(timeMs, spikeMs) {
  return Number.isFinite(timeMs) && Number.isFinite(spikeMs)
    && timeMs >= spikeMs && timeMs - spikeMs < 6;
}
