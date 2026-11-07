import React from 'react';
import { Box, Text } from '@chakra-ui/react';

// These are sampled membrane voltages, not a measurement of pain or an inferred spike.
export function voltageProbeGeometry(preview) {
  const time = preview?.time_ms, baseline = preview?.probe_baseline_mv, active = preview?.probe_active_mv;
  if (!preview?.voltage_probe || !Array.isArray(time) || time.length < 2
      || !Array.isArray(baseline) || !Array.isArray(active)
      || baseline.length !== time.length || active.length !== time.length
      || time.some((value, i) => !Number.isFinite(value) || (i > 0 && value <= time[i - 1]))
      || !baseline.every(Number.isFinite) || !active.every(Number.isFinite)) return null;
  const lo = Math.min(...baseline, ...active), hi = Math.max(...baseline, ...active);
  const padding = Math.max((hi - lo) * .08, .1), minimum = lo - padding, maximum = hi + padding;
  const path = values => values.map((value, i) => {
    const x = 38 + 250 * (time[i] - time[0]) / (time.at(-1) - time[0]);
    const y = 8 + 68 * (maximum - value) / (maximum - minimum);
    return `${i ? 'L' : 'M'}${x.toFixed(2)},${y.toFixed(2)}`;
  }).join(' ');
  return { minimum, maximum, time, baseline: path(baseline), active: path(active) };
}

export default function VoltageProbePlot({ preview, timeMs }) {
  const geometry = voltageProbeGeometry(preview);
  if (!geometry) return null;
  const { time, minimum, maximum } = geometry;
  const cursor = 38 + 250 * Math.max(0, Math.min(1, (timeMs - time[0]) / (time.at(-1) - time[0])));
  return <Box mt={2}>
    <Text fontSize="11px">Мембранное напряжение · узел {preview.voltage_probe.child_node_id}, сегмент {preview.voltage_probe.segment_index + 1}/{preview.voltage_probe.segments_per_edge}</Text>
    <svg viewBox="0 0 300 100" width="100%" role="img" aria-label="Напряжение выбранного компартмента с событиями и без них, милливольты">
      <text x="0" y="12" fill="#8A90A2" fontSize="9">{maximum.toFixed(1)}</text>
      <text x="0" y="76" fill="#8A90A2" fontSize="9">{minimum.toFixed(1)}</text>
      <text x="0" y="91" fill="#8A90A2" fontSize="9">мВ</text>
      <path d={geometry.baseline} fill="none" stroke="#9AA5BC" strokeWidth="1" strokeDasharray="3 2" />
      <path d={geometry.active} fill="none" stroke="#39DDB1" strokeWidth="1.2" />
      <line x1={cursor} x2={cursor} y1="8" y2="76" stroke="#D8DFEF" strokeWidth=".6" />
    </svg>
    <Text fontSize="10px" color="gray.400">Зелёный — с событиями; пунктир — без них. Модельное напряжение, не измерение у мухи.</Text>
    {preview.probe_morphology_sha256 && <Text fontSize="10px" color="gray.400">Маркер показывает выбранный сегмент; яркость отражает модуль разности напряжений до 20 мВ по последнему сохранённому отсчёту.</Text>}
  </Box>;
}
