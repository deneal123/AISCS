import { fieldRecordingScope } from '../../../src/features/simulator/recording/recordingScope';

test('shows the physically recorded cell count only when it is explicitly available', () => {
  expect(fieldRecordingScope({ result: { preview: { source_cells: 46 } } }))
    .toBe('E1 − REF · клеток: 46');
  expect(fieldRecordingScope({ result: { preview: { source_cells: 0 } } }))
    .toBe('E1 − REF · выбранные клетки');
  expect(fieldRecordingScope(null)).toBe('E1 − REF · выбранные клетки');
});
