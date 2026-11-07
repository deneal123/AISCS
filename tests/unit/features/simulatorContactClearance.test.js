import { resolveContactClearance } from '../../../src/features/simulator/field/contactClearance';

const simulation = { source_um: [0, 0, 0], return_um: [100, 0, 0],
  electrode_um: [0, 100, 0], reference_um: [100, 100, 0], clearance_um: 1 };

test('finds individually screened nearest positions for all intersecting contacts', async () => {
  const positions = jest.fn().mockResolvedValue({ potential_intersections: [] });
  const result = await resolveContactClearance(simulation, { potential_intersections: [{ contact_indices: [0, 2] }] }, positions, () => true);
  expect(positions.mock.calls[0][0]).toHaveLength(24);
  expect(result.adjustments).toEqual([{ index: 0, distance_um: 10 }, { index: 2, distance_um: 10 }]);
  expect(result.simulation.return_um).toEqual(simulation.return_um);
  expect(result.simulation.reference_um).toEqual(simulation.reference_um);
  expect(simulation.source_um).toEqual([0, 0, 0]);
});

test('does not accept a candidate flagged by the verified index', async () => {
  const positions = jest.fn().mockImplementation(async points => ({ potential_intersections: [
    { contact_indices: points.map((_, i) => i) },
  ] }));
  await expect(resolveContactClearance(simulation, { potential_intersections: [{ contact_indices: [0, 1, 2, 3] }] }, positions, () => true)).resolves.toBeNull();
  expect(positions).toHaveBeenCalledTimes(2);
  expect(positions.mock.calls.every(([points]) => points.length <= 64)).toBe(true);
});

test('rejects stale or malformed screening results', async () => {
  const initial = { potential_intersections: [{ contact_indices: [0] }] };
  await expect(resolveContactClearance(simulation, initial, async () => ({ potential_intersections: [] }), () => false)).rejects.toThrow('contact_draft_changed');
  await expect(resolveContactClearance(simulation, initial, async () => ({ potential_intersections: [{ contact_indices: [900] }] }), () => true)).rejects.toThrow('invalid_contact_screen');
});
