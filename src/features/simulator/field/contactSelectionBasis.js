const contactKeys = ['source_um', 'return_um', 'electrode_um', 'reference_um'];

// Record the coordinates on which a spatial selection was based, not their input formatting.
export function contactSelectionBasis(scene, manifest, values) {
  return JSON.stringify([scene, manifest, ...contactKeys.map(key =>
    Array.isArray(values?.[key]) ? values[key].map(value =>
      String(value).trim() !== '' && Number.isFinite(Number(value)) ? Number(value) : null) : null)]);
}
