import { DIFFERENTIAL_VERSION, PROBE_MASSES, STABLE_CORE, NOCICEPTIVE_ADDITIONS,
  CONTROL_ADDITIONS, nearestMass, differentialReadout, addressObservability,
  ABSOLUTE_LIMIT_MASS, OVERLAP_STARTS_MASS } from '../../../src/features/simulator/scene/nociceptiveDifferential';

test('the differential counts reproduce the measured additions at every probed mass', () => {
  expect(DIFFERENTIAL_VERSION).toBe('malecns-nociceptive-address-differential-v1');
  expect(PROBE_MASSES).toEqual([0, 100, 200, 300, 400, 500, 600]);
  for (const mass of PROBE_MASSES) {
    const readout = differentialReadout(mass);
    expect(readout.available).toBe(true);
    expect(readout.mass).toBe(mass);
    expect(readout.exact).toBe(true);
    expect(readout.nociceptive).toBe(NOCICEPTIVE_ADDITIONS[mass]);
    expect(readout.control).toBe(CONTROL_ADDITIONS[mass]);
    expect(readout.core).toBe(STABLE_CORE);
    expect(readout.nociceptive).toBeGreaterThan(readout.control);
  }
  expect(NOCICEPTIVE_ADDITIONS[0]).toBe(12);
  expect(CONTROL_ADDITIONS[0]).toBe(0);
  expect(NOCICEPTIVE_ADDITIONS[100]).toBe(13);
  expect(CONTROL_ADDITIONS[100]).toBe(0);
});

test('a mass between probes reports the nearest probe and says it is not exact', () => {
  const readout = differentialReadout(310);
  expect(readout.mass).toBe(300);
  expect(readout.exact).toBe(false);
  expect(differentialReadout('nonsense').available).toBe(false);
  expect(nearestMass(0)).toBe(0);
  expect(nearestMass(599)).toBe(600);
});

test('the measured curve has a flat tail and the control only starts at 300', () => {
  expect(NOCICEPTIVE_ADDITIONS[200]).toBe(NOCICEPTIVE_ADDITIONS[100]);
  expect(NOCICEPTIVE_ADDITIONS[600]).toBe(NOCICEPTIVE_ADDITIONS[0]);
  expect(CONTROL_ADDITIONS[0]).toBe(0);
  expect(CONTROL_ADDITIONS[100]).toBe(0);
  expect(CONTROL_ADDITIONS[300]).toBeGreaterThan(0);
});

test('the address is absolute below 300 and only a difference above 500', () => {
  expect(OVERLAP_STARTS_MASS).toBe(300);
  expect(ABSOLUTE_LIMIT_MASS).toBe(500);
  expect(addressObservability(0)).toBe('absolute');
  expect(addressObservability(200)).toBe('absolute-with-overlap');
  expect(addressObservability(300)).toBe('differential-narrowing');
  expect(addressObservability(400)).toBe('differential-narrowing');
  expect(addressObservability(500)).toBe('differential-only');
  expect(addressObservability(600)).toBe('differential-only');
  expect(addressObservability(undefined)).toBe('unknown');
  expect(differentialReadout(0).absoluteObservable).toBe(true);
  expect(differentialReadout(600).absoluteObservable).toBe(false);
});

test('the stable core is nine cells and excludes the two cells that do not survive', () => {
  expect(STABLE_CORE).toHaveLength(9);
  expect(new Set(STABLE_CORE).size).toBe(9);
  expect(STABLE_CORE).not.toContain('56710');
  expect(STABLE_CORE).not.toContain('80727');
  expect(STABLE_CORE).not.toContain('514484');
});
