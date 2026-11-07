import React, { useEffect, useRef, useState } from 'react';
import { Box, Button, HStack, Text } from '@chakra-ui/react';
import { simulationApi } from '../api';
import SignalPlot from '../recording/SignalPlot';
import { SIMULATION_THEME, SIMULATION_TRACES } from '../theme';

function RecordingMask({ label, intervals, duration, time }) {
  if (!Array.isArray(intervals)) return <Text fontSize="11px">Маска {label.toLowerCase()} недоступна.</Text>;
  const merged = intervals.reduce((rows, interval) => {
    const previous = rows.at(-1);
    if (previous && previous.end_ms === interval.start_ms && previous.valid === interval.valid && previous.saturated === interval.saturated) previous.end_ms = interval.end_ms;
    else rows.push({ ...interval });
    return rows;
  }, []);
  return <Box position="relative" mt={1}>
    <Text position="absolute" left={0} top={0} fontSize="10px" color={SIMULATION_THEME.textSecondary}>{label}</Text>
    <svg role="img" aria-label={`Маска ${label.toLowerCase()} записи`} viewBox={`0 0 ${duration} 1`} preserveAspectRatio="none" style={{ display: 'block', width: '100%', height: 12, paddingLeft: 58, paddingRight: 14, boxSizing: 'border-box' }}>
      {merged.map((interval, index) => <rect key={index} x={interval.start_ms} y="0" width={interval.end_ms - interval.start_ms} height="1" fill={interval.saturated ? '#EF6A62' : interval.valid ? '#2D5BFF' : '#EAA064'} />)}
      <line data-role="cursor" x1={time} x2={time} y1="0" y2="1" stroke="#e8eaf0" vectorEffect="non-scaling-stroke" />
    </svg>
  </Box>;
}

// The preview uses the saved currents only; editing STIM never changes this result.
export default function FieldRerecordPreview({ runId, electrode, reference, valid, original }) {
  const [state, setState] = useState({ loading: false, result: null, error: '' });
  const [time, setTime] = useState(0);
  const [kind, setKind] = useState('neural');
  const request = useRef(null);
  const key = JSON.stringify([runId, electrode, reference]);
  useEffect(() => {
    request.current?.abort();
    request.current = null;
    setState({ loading: false, result: null, error: '' });
    setTime(0);
    setKind('neural');
    return () => request.current?.abort();
  }, [key]);
  const calculate = async () => {
    if (!valid || state.loading) return;
    const controller = new AbortController();
    request.current = controller;
    setState({ loading: true, result: null, error: '' });
    try {
      const result = await simulationApi.rerecordPreview(runId, {
        electrode_um: electrode.map(Number), reference_um: reference.map(Number),
      }, controller.signal);
      if (!controller.signal.aborted) setState({ loading: false, result, error: '', key });
    } catch (error) {
      if (!controller.signal.aborted) setState({ loading: false, result: null,
        error: (error?.status ?? error?.response?.status) === 422 ? 'Проверьте положение контактов.' : 'Не удалось пересчитать запись. Повторите попытку.' });
    }
  };
  const result = state.key === key ? state.result : null;
  const signal = kind === 'total' ? result?.total_uv : kind === 'filtered'
    ? result?.acquisition?.filtered_total_uv : result?.neural_uv;
  const originalSignal = kind === 'total' ? original?.total_uv : kind === 'filtered'
    ? original?.acquisition?.filtered_total_uv : original?.neural_uv;
  return <Box mt={3} borderTop="1px solid" borderColor={SIMULATION_THEME.panelBorder} pt={3}>
    <HStack><Button size="sm" variant="outline" type="button" isDisabled={!valid} isLoading={state.loading} onClick={calculate}>Предпросмотр E1 − REF</Button>
      <Text fontSize="12px" color={SIMULATION_THEME.textSecondary}>Без повторного расчёта сети</Text></HStack>
    <Text fontSize="11px" color={SIMULATION_THEME.textSecondary} mt={1}>Используются сохранённые токи и прежняя стимуляция. Новый STIM требует отдельного расчёта.</Text>
    {state.error && <Text role="alert" fontSize="12px" color="orange.200" mt={2}>{state.error}</Text>}
    {result && <Box mt={2} aria-label="Предпросмотр новой записи"><Text fontSize="12px">{result.cells} выбранных клеток · мкВ</Text>
      <HStack spacing={1} flexWrap="wrap" rowGap={1} mt={2}>
        {[['neural', 'Нейронный'], ['total', 'С артефактом'], ['filtered', 'Регистрация']].map(([id, label]) => <Button key={id} size="xs" type="button" variant={kind === id ? 'solid' : 'outline'} aria-pressed={kind === id}
          isDisabled={id === 'total' ? !Array.isArray(original?.total_uv) || !Array.isArray(result.total_uv)
            : id === 'filtered' ? !Array.isArray(original?.acquisition?.filtered_total_uv) || !Array.isArray(result.acquisition?.filtered_total_uv) : false}
          onClick={() => setKind(id)}>{label}</Button>)}
      </HStack>
      <HStack spacing={4} flexWrap="wrap" mt={1} fontSize="11px"><Text color={SIMULATION_TRACES.current}>● Новое положение</Text><Text color={SIMULATION_TRACES.reference}>● Исходная запись</Text></HStack>
      <SignalPlot preview={{ time_ms: result.time_ms, signal_uv: signal }}
        comparison={{ time_ms: original.time_ms, signal_uv: originalSignal }} timeMs={time} onTime={setTime} />
      {kind === 'filtered' && <>
        <RecordingMask label="Новой" duration={result.time_ms.at(-1)} intervals={result.acquisition.mask_intervals} time={time} />
        <RecordingMask label="Исходной" duration={original.time_ms.at(-1)} intervals={original.acquisition.mask_intervals} time={time} />
        <Text fontSize="11px" color="orange.200">{result.acquisition.saturated_samples.some(Boolean) ? 'В новой записи есть насыщение. ' : ''}{result.acquisition.valid_samples.some(value => !value) ? 'Часть отсчётов исключена моделью обработки.' : 'Насыщение и исключённые отсчёты не обнаружены моделью обработки.'} Синий — вне маски, оранжевый — исключено, красный — насыщение; интервалы обобщены.</Text>
      </>}
      <Text fontSize="11px" color={SIMULATION_THEME.textSecondary}>Предпросмотр не сохраняет опыт и не представляет запись всей сети.</Text></Box>}
  </Box>;
}
