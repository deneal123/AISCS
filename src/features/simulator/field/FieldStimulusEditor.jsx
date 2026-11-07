import React from 'react';
import { Box, Button, ButtonGroup, FormControl, FormLabel, Input, SimpleGrid, Text } from '@chakra-ui/react';

const fields = [
  ['duration_ms', 'Длительность расчёта, мс'], ['dt_ms', 'Шаг расчёта, мс'],
  ['pulse_start_ms', 'Начало импульса, мс'], ['pulse_end_ms', 'Конец первой фазы, мс'],
  ['rise_time_ms', 'Длительность фронта, мс'], ['interphase_gap_ms', 'Межфазная пауза, мс'],
  ['conductivity_s_m', 'Проводимость, См/м'], ['clearance_um', 'Минимальный зазор, мкм'],
];

export function normalizeFieldStimulus(simulation, acquisition) {
  const keys = [...fields.map(([key]) => key), 'current_na', 'nseg_per_edge'];
  if (keys.some(key => String(simulation[key] ?? '').trim() === '' || !Number.isFinite(Number(simulation[key])))) return null;
  const result = { ...simulation, ...Object.fromEntries(keys.map(key => [key, Number(simulation[key])])) };
  const { duration_ms: duration, dt_ms: dt, pulse_start_ms: start, pulse_end_ms: end,
    rise_time_ms: rise, interphase_gap_ms: gap, pulse_shape: shape, nseg_per_edge: segments } = result;
  const count = simulation.pulse_count == null ? 1 : Number(simulation.pulse_count);
  const interval = Number(simulation.pulse_interval_ms);
  const extent = (end - start) * (shape === 'biphasic' ? 2 : 1) + (shape === 'biphasic' ? gap : 0);
  if (!Number.isSafeInteger(duration) || duration < 1 || duration > 1000 || dt <= 0
      || !Number.isFinite(duration / dt) || Math.abs(Math.round(duration / dt) * dt - duration) > 1e-9
      || !(start > 0 && end > start && end < duration) || rise < 0 || 2 * rise > end - start
      || gap < 0 || !['monophasic', 'biphasic'].includes(shape)
      || (shape === 'monophasic' && gap !== 0)
      || (shape === 'biphasic' && end + gap + end - start >= duration)
      || result.conductivity_s_m <= 0 || result.clearance_um <= 0
      || !Number.isSafeInteger(count) || count < 1 || count > 1000
      || (count > 1 && (String(simulation.pulse_interval_ms ?? '').trim() === ''
        || !Number.isFinite(interval) || interval <= extent
        || start + (count - 1) * interval + extent >= duration))
      || !Number.isSafeInteger(segments) || segments <= 0 || segments % 2 !== 1
      || (acquisition && acquisition.high_hz >= 500 / dt)) return null;
  if (count === 1) { delete result.pulse_count; delete result.pulse_interval_ms; }
  else { result.pulse_count = count; result.pulse_interval_ms = interval; }
  return result;
}

export default function FieldStimulusEditor({ simulation, disabled, onChange }) {
  return <Box as="details" mt={4}>
    <Box as="summary" cursor="pointer" fontSize="13px">Параметры электрического импульса</Box>
    <Text fontSize="11px" color="gray.400" mt={2}>Однородная проводящая среда и идеальный импульс; параметры не откалиброваны по ткани мухи.</Text>
    <ButtonGroup size="xs" isAttached mt={3}>
      {[['monophasic', 'Однофазный'], ['biphasic', 'Двухфазный']].map(([key, label]) => <Button type="button" key={key} isDisabled={disabled}
        variant={simulation.pulse_shape === key ? 'solid' : 'outline'} onClick={() => onChange('pulse_shape', key)}>{label}</Button>)}
    </ButtonGroup>
    <SimpleGrid columns={{ base: 1, md: 2 }} spacing={3} mt={3}>
      <FormControl><FormLabel fontSize="11px" htmlFor="stim-pulse-count">Количество импульсов</FormLabel>
        <Input id="stim-pulse-count" type="number" min={1} max={1000} size="sm" value={simulation.pulse_count ?? 1} isDisabled={disabled}
          onChange={event => onChange('pulse_count', event.target.value)} /></FormControl>
      {Number(simulation.pulse_count ?? 1) > 1 && <FormControl><FormLabel fontSize="11px" htmlFor="stim-pulse-interval">Интервал между началами, мс</FormLabel>
        <Input id="stim-pulse-interval" type="number" size="sm" value={simulation.pulse_interval_ms ?? ''} isDisabled={disabled}
          onChange={event => onChange('pulse_interval_ms', event.target.value)} /></FormControl>}
      {fields.map(([key, label]) => <FormControl key={key}><FormLabel fontSize="11px" htmlFor={`stim-${key}`}>{label}</FormLabel>
        <Input id={`stim-${key}`} type="number" size="sm" value={simulation[key]} isDisabled={disabled || (key === 'interphase_gap_ms' && simulation.pulse_shape === 'monophasic')}
          onChange={event => onChange(key, event.target.value)} /></FormControl>)}
    </SimpleGrid>
  </Box>;
}
