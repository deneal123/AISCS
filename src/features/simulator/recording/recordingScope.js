// The physical recording covers the reconstructed source population, not all
// graph nodes. Older recordings may not include an explicit cell count.
export function fieldRecordingScope(run) {
  const count = run?.result?.preview?.source_cells;
  return Number.isSafeInteger(count) && count > 0
    ? `E1 − REF · клеток: ${count.toLocaleString('ru-RU')}`
    : 'E1 − REF · выбранные клетки';
}
