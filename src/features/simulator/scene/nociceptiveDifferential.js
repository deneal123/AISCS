// The differential readout is the only way the nociceptive address stays observable
// once roughly 300 mechanosensory afferents are already firing (H151/H157/H158).
// It is a count of ascending cells that a mass of input adds, not a pain measure.
export const DIFFERENTIAL_VERSION = 'malecns-nociceptive-address-differential-v1';

// Mass of unknown_sensory afferents already driven, before the probe is added.
export const PROBE_MASSES = [0, 100, 200, 300, 400, 500, 600];

// Measured additions, four seeds by three control draws (probe-h157.py, probe-h158.py,
// seed 11 draw 0 for 0/200/400/600 and two further probes for the rest).
export const NOCICEPTIVE_ADDITIONS = Object.freeze({ 0: 12, 100: 13, 200: 13, 300: 15, 400: 14, 500: 12, 600: 12 });
export const CONTROL_ADDITIONS = Object.freeze({ 0: 0, 100: 0, 200: 3, 300: 5, 400: 1, 500: 4, 600: 3 });
export const ADDITION_RANGE = Object.freeze({ nociceptive: [9, 14], control: [0, 6] });

// The nine cells common to every measured nociceptive addition. The map also has
// AN01A021 (56710, 80727), which does not survive at high mass, and ANXXX196 (514484),
// which is shared with the chemosensory pool.
export const STABLE_CORE = Object.freeze(['11604', '14026', '18325', '19197', '29334',
  '32085', '512555', '513169', '515447']);

export function nearestMass(mass) {
  const value = Number(mass);
  if (!Number.isFinite(value)) return null;
  return PROBE_MASSES.reduce((best, candidate) =>
    Math.abs(candidate - value) < Math.abs(best - value) ? candidate : best, PROBE_MASSES[0]);
}

// What one can honestly say at a given mass of driven afferents.
export function differentialReadout(mass) {
  const key = nearestMass(mass);
  if (key === null) return { version: DIFFERENTIAL_VERSION, available: false };
  const nociceptive = NOCICEPTIVE_ADDITIONS[key];
  const control = CONTROL_ADDITIONS[key];
  return { version: DIFFERENTIAL_VERSION, available: true, mass: key, exact: key === Number(mass),
    nociceptive, control, ratio: control > 0 ? Number((nociceptive / control).toFixed(2)) : null,
    absoluteObservable: key === 0, core: STABLE_CORE };
}

// Where the measured curve changes shape, from probe-h159.py: at 0 and 100 the control adds
// nothing at all; from 300 the control starts adding 2 to 10 cells; from 500 the block that
// only nociceptors recruited is already firing from the base, so nothing separates it.
export const OVERLAP_STARTS_MASS = 300;
export const ABSOLUTE_LIMIT_MASS = 500;

export function addressObservability(mass) {
  const value = Number(mass);
  if (!Number.isFinite(value)) return 'unknown';
  if (value <= 0) return 'absolute';
  if (value < OVERLAP_STARTS_MASS) return 'absolute-with-overlap';
  if (value < ABSOLUTE_LIMIT_MASS) return 'differential-narrowing';
  return 'differential-only';
}
