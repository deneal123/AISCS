// Reproduced engineering example for exactly this registered graph revision.
// Values are not calibrated tissue or Drosophila physiology.
const GRAPH = '742ee0b22040d6831cb96479d468cd57f1a60d96e2004e3beb421a8d3ac936a2';

export function fieldDemoPreset(manifest) {
  if (manifest !== GRAPH) return null;
  return {
    graph_manifest_sha256: GRAPH,
    source_cells: [{ body_id: 14110, child_node_id: 3633, sampling_fraction: 1, threshold_mv: -20 }],
    replay_ids: [324531], seed: 1,
    simulation: {
      source_um: [429.056, 327.68, 228.352], return_um: [929.056, 327.68, 228.352],
      electrode_um: [419.328, 319.488, 359.92], reference_um: [919.328, 319.488, 359.92],
      current_na: -300, conductivity_s_m: .3, clearance_um: 1, duration_ms: 10,
      dt_ms: .05, pulse_start_ms: 2, pulse_end_ms: 3, rise_time_ms: .2,
      interphase_gap_ms: 0, pulse_shape: 'monophasic', nseg_per_edge: 1,
      allow_disconnected: false, source_model: 'pointsource', coordinate_frame: 'male-cns-v1.0-native-um',
    },
    synapse: { delay_ms: 2, weight_us: .00001, tau1_ms: .2, tau2_ms: 2, reversal_mv: 0 },
    acquisition: { low_hz: 100, high_hz: 3000, recovery_ms: .5, clip_uv: 1000 },
  };
}
