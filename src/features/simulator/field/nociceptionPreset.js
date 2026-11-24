// A working nociceptive stimulus for exactly this registered graph revision.
// The values are not calibrated Drosophila physiology: they are the measured
// operating point at which the field crosses the -20 mV threshold on enough
// abdominal afferents at once (about ninety) for the connectome to answer.
// Source and return sit 500 um apart along z in the abdominal neuropil, the
// reading pair is a differential contact outside any cable, and 2.4 uA for
// 100 ms is what the sweep needed. See docs 17 for every number.
const GRAPH = '742ee0b22040d6831cb96479d468cd57f1a60d96e2004e3beb421a8d3ac936a2';

export const NOCICEPTION_POINT = {
  source_um: [436.6, 385, 1009.5],
  return_um: [436.6, 385, 509.5],
  electrode_um: [423.8, 411.7, 960.9],
  reference_um: [404.8, 417.2, 466.9],
};

export function nociceptionPreset(manifest) {
  if (manifest !== GRAPH) return null;
  return {
    graph_manifest_sha256: GRAPH,
    simulation: {
      ...NOCICEPTION_POINT,
      current_na: -2400, conductivity_s_m: .3, clearance_um: 1, duration_ms: 100,
      dt_ms: .05, pulse_start_ms: 2, pulse_end_ms: 3, rise_time_ms: .2,
      interphase_gap_ms: 0, pulse_shape: 'monophasic', nseg_per_edge: 1,
      allow_disconnected: true, source_model: 'pointsource',
      coordinate_frame: 'male-cns-v1.0-native-um',
    },
  };
}

// What the measured run says, so a reader does not have to trust the panel.
export const NOCICEPTION_MEASURED = {
  crossedAfferents: 307,
  crossedTotal: 676,
  crossedAscending: 41,
  firstAscendingTick: 5,
  readingPtpUv: 1348.677,
  note: '307 из 1145 абдоминальных афферентов пересекают порог; 41 восходящая клетка отвечает через 2 мс; при удалении исходящих рёбер афферентов ответ ровно нулевой.',
};
