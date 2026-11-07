import React from 'react';
import { render, screen } from '@testing-library/react';
import VoltageProbePlot, { voltageProbeGeometry } from '../../../src/features/simulator/recording/VoltageProbePlot';

test('renders only valid saved voltage traces with explicit compartment identity', () => {
  const preview = { time_ms: [0, 1, 2], probe_baseline_mv: [-65, -64, -65],
    probe_active_mv: [-65, -20, -65], voltage_probe: { child_node_id: 9, segment_index: 0, segments_per_edge: 1 } };
  const geometry = voltageProbeGeometry(preview);
  expect(geometry.baseline).not.toEqual(geometry.active);
  render(<VoltageProbePlot preview={preview} timeMs={1} />);
  expect(screen.getByText(/узел 9, сегмент 1\/1/)).toBeInTheDocument();
  expect(screen.getByRole('img')).toHaveAttribute('aria-label', expect.stringContaining('милливольты'));
  expect(voltageProbeGeometry({ ...preview, probe_active_mv: [0, NaN, 0] })).toBeNull();
  expect(voltageProbeGeometry({ ...preview, time_ms: [0, 0, 2] })).toBeNull();
});
