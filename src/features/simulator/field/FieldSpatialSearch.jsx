import React, { useEffect, useRef, useState } from 'react';
import { Box, Button, FormControl, FormLabel, HStack, Input, Stack, Text } from '@chakra-ui/react';
import { simulationApi } from '../api';
import { candidateEligibility } from './fieldCandidateEligibility';

const PAGE_SIZE = 50;

export default function FieldSpatialSearch({ sceneRunId, simulation, sources, replay, onAdd, onAddMany, canAddMany, onReplaceMany, canReplaceMany, disabled, fragmentMode = false }) {
  const [radius, setRadius] = useState(fragmentMode ? '10' : '50');
  const [state, setState] = useState({ loading: false, rows: null, error: '' });
  const [page, setPage] = useState(0);
  const pending = useRef(null);
  const source = simulation.source_um, target = simulation.return_um;
  const electrode = simulation.electrode_um, reference = simulation.reference_um;
  const signature = JSON.stringify([sceneRunId, source, target, electrode, reference, radius]);
  const currentSignature = useRef(signature);
  currentSignature.current = signature;
  useEffect(() => {
    pending.current?.abort(); pending.current = null;
    setState({ loading: false, rows: null, error: '' }); setPage(0);
    return () => { pending.current?.abort(); pending.current = null; };
  }, [signature]);
  const valid = Boolean(sceneRunId && String(radius).trim() !== '' && Number.isFinite(Number(radius)) && Number(radius) >= 0
    && [source, target, electrode, reference].every(point => Array.isArray(point) && point.length === 3
      && point.every(value => String(value).trim() !== '' && Number.isFinite(Number(value)))));
  const find = async () => {
    if (!valid || disabled || state.loading) return;
    const controller = new AbortController(); pending.current = controller;
    setState({ loading: true, rows: null, error: '' });
    try {
      const result = await simulationApi.spatialCandidates(sceneRunId, { source_um: source.map(Number),
        return_um: target.map(Number), electrode_um: electrode.map(Number), reference_um: reference.map(Number),
        radius_um: Number(radius) }, controller.signal);
      if (!controller.signal.aborted && currentSignature.current === signature) {
        setState({ loading: false, rows: result.candidates, error: '', signature });
      }
    } catch (error) {
      const status = error?.status ?? error?.response?.status;
      if (!controller.signal.aborted && currentSignature.current === signature) setState({ loading: false, rows: null,
        error: status === 429 ? 'Другой поиск ещё выполняется. Повторите запрос после его завершения.'
          : status === 409 ? 'Запись несовместима с индексом. Выберите завершённый опыт с подтверждённой версией и числом клеток.'
          : status === 503 ? 'Проверенный индекс ещё не готов или недоступен.' : 'Не удалось выполнить поиск. Повторите запрос.' });
    } finally { if (pending.current === controller) pending.current = null; }
  };
  const occupied = new Set([...sources.map(cell => String(cell.body_id)), ...replay.map(String)]);
  const recordingIds = new Set(replay.map(String));
  const rows = state.signature === signature ? state.rows : null;
  const pages = rows ? Math.ceil(rows.length / PAGE_SIZE) : 0;
  const availability = (row, replacing = false) => candidateEligibility(row, simulation, replacing ? recordingIds : occupied);
  const visibleRows = rows?.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE) || [];
  const eligibleRows = visibleRows.filter(row => !availability(row).unavailable);
  const eligibleAll = rows?.filter(row => !availability(row).unavailable) || [];
  const replacement = rows?.filter(row => !availability(row, true).unavailable) || [];
  const pageFits = !canAddMany || canAddMany(eligibleRows);
  const allFit = !canAddMany || canAddMany(eligibleAll);
  const replacementFits = !canReplaceMany || canReplaceMany(replacement);
  return <Box as="details" mt={4}>
    <Box as="summary" cursor="pointer" fontSize="13px">Поиск отростков рядом со STIM</Box>
    <Text fontSize="11px" color="gray.400" mt={2}>Поиск измеряет расстояние до осевой линии SWC, не возбуждение. Индекс относится к снимку исходных файлов; положение в теле не зарегистрировано. При перемещении контактов повторите поиск и проверьте состав. Зазоры до всех четырёх контактов проверяются для найденных клеток.</Text>
    <HStack mt={3} align="end"><FormControl maxW="200px"><FormLabel fontSize="11px" htmlFor="field-search-radius">Радиус, мкм</FormLabel><Input id="field-search-radius" type="number" size="sm" min={0} value={radius} isDisabled={disabled} onChange={event => setRadius(event.target.value)} /></FormControl>
      <Button type="button" size="sm" variant="outline" isLoading={state.loading} isDisabled={!valid || disabled} onClick={find}>Найти</Button></HStack>
    {state.error && <Text role="alert" fontSize="12px" color="orange.200" mt={2}>{state.error}</Text>}
    {rows && <Box mt={3}>
      <Text fontSize="12px">{fragmentMode ? `Найдено: ${rows.length}. Это геометрический отбор, а не подтверждение возбуждения. Выходы клеток проверяются отдельно.` : `Найдено: ${rows.length}. Добавление и замена сохраняют положение ближайшей точки и задают условный порог −20 мВ; расчёт использует ближайший центр компартмента.`}</Text>
      {onAddMany && <Button type="button" size="xs" variant="outline" mt={2} isDisabled={disabled || !eligibleRows.length || !pageFits} onClick={() => onAddMany(eligibleRows)}>Добавить подходящие на странице ({eligibleRows.length})</Button>}
      {onAddMany && pages > 1 && <><Button type="button" size="xs" variant="outline" mt={2} ml={2} isDisabled={disabled || !eligibleAll.length || !allFit} onClick={() => onAddMany(eligibleAll)}>Добавить все подходящие ({eligibleAll.length})</Button>
        {!allFit && <Text fontSize="11px" color="orange.200" mt={1}>Все найденные клетки не помещаются в запрос. Добавляйте их страницами или уменьшите радиус поиска.</Text>}</>}
      {onReplaceMany && <><Button type="button" size="xs" variant="outline" mt={2} ml={2} isDisabled={disabled || !replacement.length || !replacementFits} onClick={() => onReplaceMany(replacement)}>Заменить источники найденными ({replacement.length})</Button>
        <Text fontSize="11px" color="gray.400" mt={1}>{fragmentMode ? 'Замена использует все подходящие найденные клетки; исключённые и расположенные дальше радиуса клетки не рассчитываются.' : 'Замена использует все подходящие результаты поиска; клетки записи сохраняются. Геометрическая близость не означает возбуждение.'}</Text>
        {!replacementFits && <Text fontSize="11px" color="orange.200" mt={1}>Состав не помещается в запрос. Уменьшите радиус поиска.</Text>}</>}
      {!pageFits && <Text fontSize="11px" color="orange.200" mt={1}>Клетки страницы не помещаются в запрос: выберите отдельные клетки или сократите состав.</Text>}
      <Stack spacing={1} mt={2}>{visibleRows.map(row => {
        const { incompatible, tooClose, recordingTooClose, unavailable } = availability(row);
        return <HStack key={row.body_id} borderBottom="1px solid" borderColor="#263453" py={1} fontSize="12px">
          <Text flex={1}>ID {row.body_id} · {row.distance_um.toFixed(1)} мкм · STIM{row.contact === 0 ? '+' : '−'}{row.isolated_root ? ' · одиночная точка' : ` · сегмент ${row.child_node_id}`}{incompatible ? ' · геометрия не поддерживается текущим решателем' : ''}{tooClose ? ' · STIM внутри зазора' : ''}{recordingTooClose ? ' · E1 или REF внутри зазора' : ''}</Text>
          {onAdd && <Button type="button" size="xs" variant="ghost" isDisabled={disabled || unavailable} onClick={() => onAdd(row)}>Добавить</Button>}
        </HStack>;
      })}</Stack>
      {pages > 1 && <HStack mt={2}><Button type="button" size="xs" isDisabled={page === 0} onClick={() => setPage(value => value - 1)}>Назад</Button><Text fontSize="11px">{page + 1} / {pages}</Text><Button type="button" size="xs" isDisabled={page + 1 >= pages} onClick={() => setPage(value => value + 1)}>Далее</Button></HStack>}
    </Box>}
  </Box>;
}
