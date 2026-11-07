import React from 'react';
import { Box, Button, FormControl, FormLabel, HStack, Input, Stack, Text } from '@chakra-ui/react';

const positiveInteger = value => String(value).trim() !== '' && Number.isSafeInteger(Number(value)) && Number(value) > 0;
export function normalizeFieldPopulation(sources, replay) {
  if (!Array.isArray(sources) || !sources.length || !Array.isArray(replay) || !replay.length
      || sources.some(cell => !positiveInteger(cell.body_id) || !positiveInteger(cell.child_node_id)
        || String(cell.threshold_mv).trim() === '' || !Number.isFinite(Number(cell.threshold_mv))
        || (cell.morphology_sha256 != null && !/^[a-f0-9]{64}$/.test(cell.morphology_sha256))
        || (cell.sampling_fraction != null && (String(cell.sampling_fraction).trim() === ''
          || !Number.isFinite(Number(cell.sampling_fraction)) || Number(cell.sampling_fraction) < 0
          || Number(cell.sampling_fraction) > 1)))
      || replay.some(id => !positiveInteger(id))) return null;
  const sourceCells = sources.map(cell => ({ body_id: Number(cell.body_id), child_node_id: Number(cell.child_node_id), threshold_mv: Number(cell.threshold_mv),
    ...(cell.sampling_fraction == null ? {} : { sampling_fraction: Number(cell.sampling_fraction) }),
    ...(cell.morphology_sha256 == null ? {} : { morphology_sha256: cell.morphology_sha256 }) }));
  const replayIds = replay.map(Number), ids = [...sourceCells.map(cell => cell.body_id), ...replayIds];
  return new Set(ids).size === ids.length ? { source_cells: sourceCells, replay_ids: replayIds } : null;
}

export default function FieldPopulationEditor({ sources, replay, onChange, disabled }) {
  const sourceChange = (index, key, value) => onChange(sources.map((cell, i) => {
    if (i !== index) return cell;
    const next = { ...cell, [key]: value };
    if (key === 'body_id' || key === 'child_node_id') delete next.sampling_fraction;
    if (key === 'body_id') delete next.morphology_sha256;
    return next;
  }), replay);
  const replayChange = (index, value) => onChange(sources, replay.map((id, i) => i === index ? value : id));
  return <Box as="details" mt={4}>
    <Box as="summary" cursor="pointer" fontSize="13px">Клетки модели · {sources.length} источников, {replay.length} для записи</Box>
    <Text fontSize="11px" color="gray.400" mt={2}>Укажите зарегистрированные ID, ID дочерней вершины SWC и порог пересечения напряжения. Подбор вершины и порога — допущение модели, а не подтверждённое место возникновения спайка.</Text>
    <Stack spacing={3} mt={3}>
      {sources.map((cell, index) => <HStack key={index} align="end" spacing={2}>
        {[['body_id', 'ID источника'], ['child_node_id', 'Вершина SWC'], ['threshold_mv', 'Порог, мВ']].map(([key, label]) => <FormControl key={key}>
          <FormLabel fontSize="11px">{label}</FormLabel><Input aria-label={`${label} ${index + 1}`} type="number" size="sm" value={cell[key]} isDisabled={disabled} onChange={event => sourceChange(index, key, event.target.value)} />
        </FormControl>)}
        <Button size="sm" variant="ghost" aria-label={`Удалить источник ${index + 1}`} isDisabled={disabled || sources.length === 1} onClick={() => onChange(sources.filter((_, i) => i !== index), replay)}>×</Button>
      </HStack>)}
      {sources.some(cell => cell.sampling_fraction != null) && <Text fontSize="11px" color="gray.400">Для найденных сегментов сохраняется положение ближайшей точки. Расчёт использует ближайший центр компартмента; фактическое положение записывается в результат.</Text>}
      <Button size="xs" alignSelf="start" variant="outline" isDisabled={disabled} onClick={() => onChange([...sources, { body_id: '', child_node_id: '', threshold_mv: -20 }], replay)}>Добавить источник</Button>
      {replay.map((id, index) => <HStack key={index} align="end" spacing={2} maxW="360px"><FormControl><FormLabel fontSize="11px">ID клетки записи</FormLabel><Input aria-label={`ID клетки записи ${index + 1}`} type="number" size="sm" value={id} isDisabled={disabled} onChange={event => replayChange(index, event.target.value)} /></FormControl>
        <Button size="sm" variant="ghost" aria-label={`Удалить клетку записи ${index + 1}`} isDisabled={disabled || replay.length === 1} onClick={() => onChange(sources, replay.filter((_, i) => i !== index))}>×</Button></HStack>)}
      <Button size="xs" alignSelf="start" variant="outline" isDisabled={disabled} onClick={() => onChange(sources, [...replay, ''])}>Добавить клетку записи</Button>
    </Stack>
  </Box>;
}
