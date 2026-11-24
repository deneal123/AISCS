// A working nociceptive stimulus for exactly this registered graph revision.
// The values are not calibrated Drosophila physiology: they are the measured
// operating point at which the field crosses the -20 mV threshold on enough
// abdominal afferents at once for the connectome to answer, at a contact that
// passes the audited cable screen. Source and return sit 500 um apart along z
// in the abdominal neuropil, the reading pair is a differential contact
// outside any cable, and 9.6 uA for 100 ms is what the sweep needed there.
// See docs 17 for every number and for what this mode does not prove.
const GRAPH = '742ee0b22040d6831cb96479d468cd57f1a60d96e2004e3beb421a8d3ac936a2';

// Screened against verified-bounds-v2/verified-radii-v1/verified-segments-v1:
// all four points clear every cable by at least the 1 um clearance.
export const NOCICEPTION_POINT = {
  source_um: [480, 390, 1040],
  return_um: [480, 390, 540],
  electrode_um: [423.8, 411.7, 960.9],
  reference_um: [444.8, 417.2, 466.9],
};

export function nociceptionPreset(manifest) {
  if (manifest !== GRAPH) return null;
  return {
    graph_manifest_sha256: GRAPH,
    simulation: {
      ...NOCICEPTION_POINT,
      current_na: -9600, conductivity_s_m: .3, clearance_um: 1, duration_ms: 100,
      dt_ms: .05, pulse_start_ms: 2, pulse_end_ms: 3, rise_time_ms: .2,
      interphase_gap_ms: 0, pulse_shape: 'monophasic', nseg_per_edge: 1,
      allow_disconnected: true, source_model: 'pointsource',
      coordinate_frame: 'male-cns-v1.0-native-um',
    },
  };
}

// What the measured run says, so a reader does not have to trust the panel.
export const NOCICEPTION_MEASURED = {
  crossedAfferents: 403,
  crossedTotal: 1220,
  crossedAscending: 62,
  firstAscendingTick: 5,
  readingPtpUv: 2670.323,
  note: '403 из 1145 абдоминальных афферентов пересекают порог; 62 восходящие клетки отвечают через 2 мс; при удалении исходящих рёбер афферентов ответ ровно нулевой. Контакты проходят проверку кабелей с зазором 1 мкм.',
};
