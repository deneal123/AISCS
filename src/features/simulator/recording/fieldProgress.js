// The backend contract reports model ticks for the network and neuron counts for field preparation.
export function validFieldProgress(progress) {
  if (!progress || typeof progress !== 'object' || Array.isArray(progress)
      || Object.keys(progress).length !== 3
      || !Number.isInteger(progress.done) || !Number.isInteger(progress.total)) return false;
  const { phase, done, total } = progress;
  if (phase === 'field') return total > 0 && total <= 166700 && done >= 0 && done <= total;
  if (phase === 'field_verification') return done === 0 && total === 0;
  if (phase === 'network') return done === 0 && total === 0
    || total > 0 && total <= 1000 && done >= 0 && done <= total;
  return false;
}
