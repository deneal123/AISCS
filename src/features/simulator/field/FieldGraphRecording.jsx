import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { executorStartError } from '../executorStartError';
import { Box, Button, ButtonGroup, Checkbox, FormControl, FormLabel, HStack, Input, Select, SimpleGrid, Text } from '@chakra-ui/react';
import { simulationApi } from '../api';
import SignalPlot from '../recording/SignalPlot';
import StimulusPlot from '../recording/StimulusPlot';
import FieldContactScene from './FieldContactScene';
import { fieldDemoPreset } from './fieldDemoPreset';
import FieldNetworkScene from './FieldNetworkScene';
import FieldPopulationEditor, { normalizeFieldPopulation } from './FieldPopulationEditor';
import FieldSpatialSearch from './FieldSpatialSearch';
import { contactSelectionBasis } from './contactSelectionBasis';
import FieldContactScreen from './FieldContactScreen';
import FieldStimulusEditor, { normalizeFieldStimulus } from './FieldStimulusEditor';
import FieldRerecordPreview from './FieldRerecordPreview';
import { SIMULATION_THEME } from '../theme';

const active = new Set(['queued', 'preparing', 'running', 'publishing', 'cancelling']);
export const sourceFromCandidate = candidate => ({ body_id: candidate.body_id, child_node_id: candidate.child_node_id,
  threshold_mv: -20, sampling_fraction: candidate.edge_fraction,
  ...(/^[a-f0-9]{64}$/.test(candidate.source_sha256 || '') ? { morphology_sha256: candidate.source_sha256 } : {}) });

// Backend accepts at most 20,000 characters in Python's JSON representation.
// Account conservatively for ASCII escaping and its default separator spaces.
export function fieldConfigurationFits(configuration) {
  const json = JSON.stringify(configuration);
  const escapedLength = Array.from(json).reduce((length, character) => length
    + (character.codePointAt(0) > 0xffff ? 12 : character.codePointAt(0) > 0x7f ? 6 : 1)
    + Number(character === ',' || character === ':'), 0);
  return escapedLength <= 19000;
}

// These experiments are independent of the currently displayed scene and its clock.
export default function FieldGraphRecording({ sceneRunId, sceneManifest, sceneDescription, onShowOnBody, incomingContacts, onConsumeContacts, onPlaceContacts }) {
  const [state, setState] = useState({ loading: true, items: [], selected: null, error: false });
  const [retry, setRetry] = useState(0);
  const [time, setTime] = useState(0);
  const [draft, setDraft] = useState(null);
  const [selectionBasis, setSelectionBasis] = useState(null);
  const [sending, setSending] = useState(false);
  const [submitError, setSubmitError] = useState(false);
  const [showGraph, setShowGraph] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [signalKind, setSignalKind] = useState('neural');
  const initialContactRunId = useRef(incomingContacts?.fieldRunId).current;
  const playbackTime = useRef(0);
  playbackTime.current = time;
  const requestId = useRef(null);
  const selectedRunId = useRef(null);
  useEffect(() => {
    const controller = new AbortController();
    let timer;
    async function load() {
      try {
        const result = await simulationApi.fieldGraphRuns(controller.signal);
        const items = result.items || [];
        const latest = items.find(item => item.id === selectedRunId.current && item.state === 'completed')
          || items.find(item => item.id === initialContactRunId && item.state === 'completed')
          || items.find(item => item.state === 'completed');
        const selected = latest ? await simulationApi.get(latest.id, controller.signal) : null;
        if (controller.signal.aborted) return;
        setState({ loading: false, items, selected, error: false, unavailable: false });
        if (items.some(item => active.has(item.state))) timer = setTimeout(load, 10000);
      } catch (error) {
        if (controller.signal.aborted) return;
        if ((error?.status ?? error?.response?.status) === 404) setState({ loading: false, items: [], selected: null, error: false, unavailable: true });
        else setState(previous => ({ ...previous, loading: false, error: true }));
      }
    }
    load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [retry, initialContactRunId]);
  useEffect(() => {
    if (!incomingContacts || incomingContacts.kind === 'fragments') return;
    const original = incomingContacts.configuration || (state.selected?.id === incomingContacts.fieldRunId ? state.selected.configuration : null);
    if (!original || original.graph_manifest_sha256 !== sceneManifest) return;
    const keys = ['source_um', 'return_um', 'electrode_um', 'reference_um'];
    const coordinates = Object.fromEntries(keys.map(key => [key, incomingContacts.simulation[key]]));
    setSelectionBasis(contactSelectionBasis(sceneRunId, sceneManifest, original.simulation));
    setDraft({ ...original, simulation: { ...original.simulation, ...coordinates } });
    requestId.current = null; setSubmitError(false); onConsumeContacts?.();
  }, [incomingContacts, state.selected, onConsumeContacts, sceneRunId, sceneManifest]);
  const preview = state.selected?.result?.preview;
  const signal = signalKind === 'filtered' ? preview?.acquisition?.filtered_total_uv
    : signalKind === 'total' ? preview?.total_uv : preview?.neural_uv;
  const chart = useMemo(() => preview && Array.isArray(signal) && ({ time_ms: preview.time_ms, signal_uv: signal }), [preview, signal]);
  const duration = preview?.time_ms?.at(-1) || 0;
  useLayoutEffect(() => { setTime(0); setPlaying(false); setSignalKind('neural'); }, [state.selected?.id]);
  useEffect(() => {
    if (!playing || !duration) return undefined;
    const start = performance.now(), initial = playbackTime.current;
    let frame;
    const tick = now => {
      const next = Math.min(duration, initial + (now - start) * .01);
      setTime(next);
      if (next < duration) frame = requestAnimationFrame(tick); else setPlaying(false);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, duration]);
  if (state.loading) return null;
  const newest = state.items[0];
  const acquisition = preview?.acquisition;
  const fullVoltage = preview?.source_all_compartments_voltage_range_mv;
  const replayVoltage = preview?.replay_all_compartments_voltage_range_mv;
  const voltageChecks = [fullVoltage || preview?.source_voltage_range_mv, replayVoltage].filter(Boolean);
  const invalid = acquisition?.valid_samples?.some(value => !value);
  const saturated = acquisition?.saturated_samples?.some(Boolean);
  const contactNames = [['source_um', 'STIM+'], ['return_um', 'STIM−'], ['electrode_um', 'E1'], ['reference_um', 'REF']];
  const updateContact = (key, index, value) => {
    setDraft(previous => ({ ...previous, simulation: { ...previous.simulation,
      [key]: previous.simulation[key].map((coordinate, i) => i === index ? value : coordinate) } }));
    requestId.current = null; setSubmitError(false);
  };
  const population = draft && normalizeFieldPopulation(draft.source_cells, draft.replay_ids);
  const stimulus = draft && normalizeFieldStimulus(draft.simulation, draft.acquisition);
  const numericDraft = draft && { ...draft, ...population, simulation: { ...stimulus,
    ...Object.fromEntries(contactNames.map(([key]) => [key, draft.simulation[key].map(Number)])),
  } };
  const values = draft && [...contactNames.flatMap(([key]) => draft.simulation[key]), draft.simulation.current_na];
  const distance = (a, b) => Math.hypot(...a.map((value, index) => value - b[index]));
  const fitsRequest = numericDraft && fieldConfigurationFits(numericDraft);
  const validDraft = Boolean(draft && population && stimulus && fitsRequest && values.every(value => String(value).trim() !== '' && Number.isFinite(Number(value))) &&
    distance(numericDraft.simulation.source_um, numericDraft.simulation.return_um) > 2 * numericDraft.simulation.clearance_um &&
    distance(numericDraft.simulation.electrode_um, numericDraft.simulation.reference_um) > 2 * numericDraft.simulation.clearance_um);
  const validRecordingContacts = Boolean(draft && ['electrode_um', 'reference_um'].every(key => draft.simulation[key].every(value => String(value).trim() !== '' && Number.isFinite(Number(value)))) &&
    distance(numericDraft.simulation.electrode_um, numericDraft.simulation.reference_um) > 2 * Number(draft.simulation.clearance_um));
  const compatibleScene = Boolean(draft && sceneRunId && sceneManifest === draft.graph_manifest_sha256);
  const staleSelection = Boolean(draft && selectionBasis !== null &&
    selectionBasis !== contactSelectionBasis(sceneRunId, sceneManifest, draft.simulation));
  const submit = async event => {
    event.preventDefault();
    if (!validDraft || staleSelection || sending) return;
    requestId.current ||= crypto.randomUUID();
    setSending(true); setSubmitError(false);
    try {
      await simulationApi.createFieldGraph({ request_id: requestId.current, title: 'Электрическая стимуляция', configuration: numericDraft });
      requestId.current = null; selectedRunId.current = null; setDraft(null); setSelectionBasis(null); setRetry(value => value + 1);
    } catch (error) {
      const status = error?.status ?? error?.response?.status;
      setSubmitError(status === 422 ? 'invalid' : status === 409 ? 'conflict' : 'uncertain');
    }
    finally { setSending(false); }
  };
  return <Box as="section" aria-label="Электрическая стимуляция: отдельный расчёт" data-run-id={state.selected?.id || ''} borderTop="1px solid" borderColor={SIMULATION_THEME.panelBorder} pt={4}>
    <Text fontSize="14px" fontWeight="600">Электрическая стимуляция · отдельный расчёт</Text>
    <Text fontSize="12px" color={SIMULATION_THEME.textSecondary} mt={1}>Запись выбранных клеток; односторонняя модель без обратной связи. Координаты заданы в исходной системе MaleCNS и не привязаны к текущей сцене.</Text>
    {state.items.filter(item => item.state === 'completed').length > 1 && <Select size="sm" mt={2}
      aria-label="Завершённый электрический расчёт" value={state.selected?.id || ''}
      onChange={event => { selectedRunId.current = event.target.value; setRetry(value => value + 1); }}>
      {state.items.filter(item => item.state === 'completed').map(item => <option key={item.id} value={item.id}>
        {item.title || 'Электрический расчёт'} · {item.id.slice(0, 8)}
      </option>)}
    </Select>}
    {state.unavailable && <Text fontSize="12px" color="orange.200" mt={2} role="status">Эта версия backend не поддерживает отдельный электрический расчёт.</Text>}
    {newest?.state === 'failed' && executorStartError(newest.error) && <Text fontSize="12px" color="orange.200" mt={1} role="alert">{executorStartError(newest.error)}</Text>}
    {incomingContacts && !state.loading && !incomingContacts.configuration && state.selected?.id !== incomingContacts.fieldRunId && <Text fontSize="12px" color="orange.200" mt={2} role="alert">Исходный электрический расчёт недоступен; выбранные на модели положения не применены.</Text>}
    {state.items.some(item => active.has(item.state)) && <Text fontSize="12px" mt={1}>Расчёт выполняется…</Text>}
    {preview && newest?.id !== state.selected.id && <Text fontSize="12px" color={SIMULATION_THEME.textSecondary} mt={1}>Показан предыдущий завершённый расчёт{newest?.state === 'failed' ? '; последний завершился ошибкой' : newest?.state === 'cancelled' ? '; последний остановлен' : ''}.</Text>}
    {newest?.state === 'failed' && newest.error === 'executor_contact_clearance' && <Text fontSize="12px" color="orange.200" mt={1} role="alert">Контакт слишком близок к восстановленному отростку. Измените положение контактов и повторите расчёт.</Text>}
    {newest?.state === 'failed' && newest.error === 'executor_contact_screen_unavailable' && <Text fontSize="12px" color="orange.200" mt={1} role="alert">Данные для проверки положения контактов недоступны. Проверьте готовность индексов и повторите расчёт.</Text>}
    {newest?.state === 'failed' && newest.error === 'executor_morphology_changed' && <Text fontSize="12px" color="orange.200" mt={1} role="alert">Морфология выбранной клетки изменилась после поиска. Повторите поиск и заново выберите источники.</Text>}
    {preview?.source_voltage_range_mv && <Text fontSize="12px" color={SIMULATION_THEME.textSecondary} mt={2}>
      Напряжение в выбранных компартментах: {preview.source_voltage_range_mv.minimum.toFixed(1)}…{preview.source_voltage_range_mv.maximum.toFixed(1)} мВ.
    </Text>}
    {fullVoltage && <Text fontSize="12px" color={SIMULATION_THEME.textSecondary} mt={1}>
      Диапазон всех компартментов источников по сводке решателя: {fullVoltage.minimum.toFixed(1)}…{fullVoltage.maximum.toFixed(1)} мВ; полные трассы не сохранены.
    </Text>}
    {!preview?.source_compartment_crossings && preview?.source_unobserved_threshold_candidates > 0 && <Text fontSize="12px" color="orange.200" mt={1} role="alert">
      Возможный пропуск: {preview.source_unobserved_threshold_candidates}. Порог достигнут вне выбранного компартмента, который не дал события. Нужна проверка трасс; возбуждение не подтверждено.
    </Text>}
    {preview?.source_compartment_crossings && (preview.source_compartment_crossings.outside_selected_only > 0 || preview.source_compartment_crossings.earlier_than_selected > 0 || preview.source_compartment_crossings.initial_above_sources > 0) && <Text fontSize="12px" color="orange.200" mt={1} role="alert">
      Пороговые переходы вне выбранного участка: без его события — {preview.source_compartment_crossings.outside_selected_only}; раньше его события — {preview.source_compartment_crossings.earlier_than_selected}. Источников с начальным превышением порога — {preview.source_compartment_crossings.initial_above_sources}. Переходы модели не подтверждают спайки.
    </Text>}
    {preview?.compartment_bin_coverage?.sources_with_unrepresented_bins > 0 && <Text fontSize="12px" color="orange.200" mt={1} role="alert">
      У {preview.compartment_bin_coverage.sources_with_unrepresented_bins} источников есть пороговые переходы в других миллисекундных интервалах, чем события выбранного участка: {preview.compartment_bin_coverage.unrepresented_source_bins} интервалов. Они не переданы в граф; это не подтверждает отдельные спайки.
    </Text>}
    {replayVoltage && <Text fontSize="12px" color={SIMULATION_THEME.textSecondary} mt={1}>
      Диапазон компартментов клеток записи по сводке решателя: {replayVoltage.minimum.toFixed(1)}…{replayVoltage.maximum.toFixed(1)} мВ; полные трассы не сохранены.
    </Text>}
    {preview && !preview.source_voltage_range_mv && <Text fontSize="12px" color="orange.200" mt={2}>Для этой записи контроль напряжения выбранных компартментов не сохранён.</Text>}
    {voltageChecks.some(range => range.minimum < -200 || range.maximum > 100) && <Text fontSize="12px" color="orange.200" mt={1} role="alert">
      Значения выходят за инженерный контрольный диапазон −200…+100 мВ. Результат требует проверки параметров и численной устойчивости; диапазон не является биологической калибровкой.
    </Text>}
    {state.error && <HStack fontSize="12px" role="status"><Text>Не удалось обновить отдельную запись.</Text><Button size="xs" variant="ghost" onClick={() => setRetry(value => value + 1)}>Повторить</Button></HStack>}
    {chart && <>
      <Text fontSize="12px" mt={3}>E1 − REF, мкВ · {preview.source_cells + preview.replay_cells} выбранных клеток</Text>
      <ButtonGroup size="xs" isAttached mt={2} mb={2}>
        {[['neural', 'Нейронный компонент'], ['total', 'С артефактом'], ['filtered', 'Модель регистрации']].map(([key, label]) => <Button key={key} type="button" variant={signalKind === key ? 'solid' : 'outline'}
          isDisabled={key === 'filtered' ? !Array.isArray(preview.acquisition?.filtered_total_uv) : key === 'total' && !Array.isArray(preview.total_uv)} onClick={() => setSignalKind(key)}>{label}</Button>)}
      </ButtonGroup>
      <StimulusPlot time={preview.time_ms} values={preview.stimulus_fraction} timeMs={time}
        onTime={value => { setPlaying(false); setTime(value); }} />
      {Number.isFinite(state.selected.configuration?.simulation?.current_na) && <Text fontSize="11px" color={SIMULATION_THEME.textSecondary} ml="58px">Ток STIM = форма импульса × {state.selected.configuration.simulation.current_na} нА.</Text>}
      <SignalPlot preview={chart} timeMs={Math.min(time, chart.time_ms.at(-1))} onTime={value => { setPlaying(false); setTime(value); }} />
      <HStack mt={2}><Button size="xs" variant="outline" onClick={() => { if (time >= duration) setTime(0); setPlaying(value => !value); }}>{playing ? 'Пауза' : 'Воспроизвести'}</Button><Text fontSize="11px" color={SIMULATION_THEME.textSecondary}>Замедление ×100 · {time.toFixed(1)} / {duration.toFixed(1)} мс</Text></HStack>
      <Text fontSize="11px" color={SIMULATION_THEME.textSecondary}>{signalKind === 'neural' ? 'Расчётный нейронный компонент без артефакта.' : signalKind === 'total' ? 'Сумма нейронного компонента и модельного артефакта стимуляции.' : 'Результат модельного фильтра и ограничения амплитуды; исключённые интервалы отмечены ниже.'} Параметры не откалиброваны; это не запись всей сети.</Text>
      {sceneRunId && sceneDescription && state.selected.configuration?.graph_manifest_sha256 === sceneManifest && <>
        {onShowOnBody && <Button size="sm" variant="outline" mt={3} mr={2} onClick={() => onShowOnBody(state.selected)}>Показать события на модели мухи</Button>}
        <Button size="sm" variant="outline" mt={3} aria-pressed={showGraph} onClick={() => setShowGraph(value => !value)}>{showGraph ? 'Скрыть события на графе' : 'Показать события на графе'}</Button>
        {showGraph && <FieldNetworkScene sceneRunId={sceneRunId} description={sceneDescription} fieldRun={state.selected} timeMs={time} />}
      </>}
      {Array.isArray(preview.network_spikes_by_ms) && <Box mt={3}>
        <Text fontSize="12px">События модели сети · {preview.network_spikes_by_ms.reduce((sum, count) => sum + count, 0)} · шаг 1 мс</Text>
        <svg role="img" aria-label="События сетевой модели по миллисекундам" viewBox={`0 0 ${preview.network_spikes_by_ms.length - 1} 1`} preserveAspectRatio="none" style={{ display: 'block', width: '100%', height: 24, marginTop: 4, paddingLeft: 58, paddingRight: 14, boxSizing: 'border-box' }}>
          {preview.network_spikes_by_ms.map((count, tick) => count > 0 && <line key={tick} x1={tick} x2={tick} y1="1" y2={1 - count / Math.max(...preview.network_spikes_by_ms)} stroke="#46D5AA" vectorEffect="non-scaling-stroke" />)}
          <line data-role="cursor" x1={time} x2={time} y1="0" y2="1" stroke="#e8eaf0" vectorEffect="non-scaling-stroke" />
        </svg>
        <Text fontSize="11px" color={SIMULATION_THEME.textSecondary}>Время этой модели не управляет текущей сценой.</Text>
      </Box>}
      {acquisition && <Box mt={3}>
        <Text fontSize="12px">Регистрация: {saturated ? 'обнаружено насыщение' : invalid ? 'есть исключённые интервалы' : 'насыщение не обнаружено'}</Text>
        <svg role="img" aria-label="Маска обработки записи: синий — вне маски, оранжевый — исключено моделью, красный — насыщение" viewBox={`0 0 ${preview.time_ms.at(-1)} 1`} preserveAspectRatio="none" style={{ display: 'block', width: '100%', height: 12, marginTop: 6, paddingLeft: 58, paddingRight: 14, boxSizing: 'border-box' }}>
          {acquisition.mask_intervals.map((interval, index) => <rect key={index} x={interval.start_ms} y="0" width={interval.end_ms - interval.start_ms} height="1" fill={interval.saturated ? '#EF6A62' : interval.valid ? '#2D5BFF' : '#EAA064'} />)}
          <line data-role="cursor" x1={time} x2={time} y1="0" y2="1" stroke="#e8eaf0" vectorEffect="non-scaling-stroke" />
        </svg>
        <Text fontSize="11px" color={SIMULATION_THEME.textSecondary} mt={1}>Синий — вне маски · оранжевый — исключено моделью · красный — насыщение. Отсутствие маски не подтверждает точность сигнала. Интервалы обобщены для предпросмотра.</Text>
      </Box>}
    </>}
    {preview && !draft && <Button size="sm" variant="outline" mt={3} onClick={() => { setDraft(JSON.parse(JSON.stringify(state.selected.configuration))); setSelectionBasis(contactSelectionBasis(sceneRunId, sceneManifest, state.selected.configuration.simulation)); setSubmitError(false); }}>Изменить контакты и рассчитать</Button>}
    {!preview && !draft && !state.items.some(item => active.has(item.state)) && <Box mt={3}>
      <Text fontSize="12px" color={SIMULATION_THEME.textSecondary}>Начальный пример использует две выбранные клетки, условные параметры и демонстрационный ток; насыщение записи возможно.</Text>
      <Button size="sm" variant="outline" mt={2} isDisabled={state.unavailable || state.error || !sceneRunId || !fieldDemoPreset(sceneManifest)}
        onClick={() => { setDraft(fieldDemoPreset(sceneManifest)); setSelectionBasis(null); setSubmitError(false); }}>Настроить первый расчёт</Button>
      {(!sceneRunId || !fieldDemoPreset(sceneManifest)) && <Text fontSize="11px" mt={2} color={SIMULATION_THEME.textSecondary}>Для примера выберите завершённый опыт с совместимой версией MaleCNS. Доступность морфологии и синапсов проверяется сервисом.</Text>}
    </Box>}
    {draft && <Box as="form" noValidate onSubmit={submit} mt={4}>
      <Text fontSize="12px" color={SIMULATION_THEME.textSecondary} mb={3}>Координаты контактов в исходной системе MaleCNS, мкм. Расчёт использует клетки предыдущего опыта и не изменяет электроды сцены.</Text>
      {onPlaceContacts && <Button type="button" size="sm" variant="outline" mb={3} isDisabled={!compatibleScene || !validDraft || sending} onClick={() => onPlaceContacts({ kind: 'field', fieldRunId: state.selected?.id, configuration: numericDraft, simulation: numericDraft.simulation })}>Разместить электроды на модели</Button>}
      {!compatibleScene && <Text fontSize="12px" color="orange.200" mb={2}>Морфология и поиск рядом со STIM доступны после выбора сцены с той же версией графа.</Text>}
      <FieldContactScene runId={compatibleScene ? sceneRunId : null} manifest={compatibleScene ? sceneManifest : null} bodyIds={population ? [...population.source_cells.map(cell => String(cell.body_id)), ...population.replay_ids.map(String)] : []}
        coordinates={draft.simulation} disabled={sending} onChange={(key, point) => {
          setDraft(previous => ({ ...previous, simulation: { ...previous.simulation, [key]: point } }));
          requestId.current = null; setSubmitError(false);
        }} />
      {state.selected?.configuration?.retain_currents === true && state.selected?.result?.manifest?.current_manifest_sha256 && <FieldRerecordPreview
        runId={state.selected.id} electrode={draft.simulation.electrode_um} reference={draft.simulation.reference_um} valid={validRecordingContacts} original={preview} />}
      <SimpleGrid columns={{ base: 1, md: 2 }} spacing={3}>
        {contactNames.map(([key, label]) => <FormControl key={key}><FormLabel fontSize="12px">{label} · X / Y / Z</FormLabel><HStack>
          {['X', 'Y', 'Z'].map((axis, index) => <Input key={axis} aria-label={`${label} ${axis}, мкм`} size="sm" type="number" value={draft.simulation[key][index]} isDisabled={sending} onChange={event => updateContact(key, index, event.target.value)} />)}
        </HStack></FormControl>)}
      </SimpleGrid>
      <FieldContactScreen sceneRunId={compatibleScene ? sceneRunId : null}
        simulation={draft.simulation} disabled={sending} onSelectContact={(index, point) => {
          const key = contactNames[index][0];
          setDraft(previous => ({ ...previous, simulation: { ...previous.simulation, [key]: point } }));
          requestId.current = null; setSubmitError(false);
        }} />
      <FormControl mt={3} maxW="220px"><FormLabel fontSize="12px" htmlFor="field-current">Ток STIM, нА</FormLabel><Input id="field-current" size="sm" type="number" value={draft.simulation.current_na} isDisabled={sending} onChange={event => { setDraft(previous => ({ ...previous, simulation: { ...previous.simulation, current_na: event.target.value } })); requestId.current = null; setSubmitError(false); }} /></FormControl>
      <FormControl mt={3} maxW="220px"><FormLabel fontSize="12px" htmlFor="field-nseg">Компартментов на сегмент</FormLabel><Input id="field-nseg" size="sm" type="number" min={1} step={2} value={draft.simulation.nseg_per_edge} isDisabled={sending} onChange={event => { setDraft(previous => ({ ...previous, simulation: { ...previous.simulation, nseg_per_edge: event.target.value } })); requestId.current = null; setSubmitError(false); }} /><Text fontSize="11px" color={SIMULATION_THEME.textSecondary} mt={1}>Нечётное число. Большее значение повышает разрешение и стоимость расчёта; точность требует проверки сходимости.</Text></FormControl>
      <FieldStimulusEditor simulation={draft.simulation} disabled={sending} onChange={(key, value) => {
        setDraft(previous => ({ ...previous, simulation: { ...previous.simulation, [key]: value,
          ...(key === 'pulse_shape' && value === 'monophasic' ? { interphase_gap_ms: 0 } : {}) } }));
        requestId.current = null; setSubmitError(false);
      }} />
      <FieldPopulationEditor sources={draft.source_cells || []} replay={draft.replay_ids || []} disabled={sending} onChange={(sources, replay) => {
        if (JSON.stringify(sources.map(cell => String(cell.body_id))) !== JSON.stringify((draft.source_cells || []).map(cell => String(cell.body_id)))) setSelectionBasis(contactSelectionBasis(sceneRunId, sceneManifest, draft.simulation));
        setDraft(previous => ({ ...previous, source_cells: sources, replay_ids: replay })); requestId.current = null; setSubmitError(false);
      }} />
      <FieldSpatialSearch sceneRunId={compatibleScene ? sceneRunId : null} simulation={draft.simulation} sources={draft.source_cells || []} replay={draft.replay_ids || []} disabled={sending} canAddMany={candidates => fieldConfigurationFits({ ...draft, source_cells: [...draft.source_cells, ...candidates.map(sourceFromCandidate)] })} canReplaceMany={candidates => fieldConfigurationFits({ ...draft, source_cells: candidates.map(sourceFromCandidate) })} onReplaceMany={candidates => {
        setDraft(previous => ({ ...previous, source_cells: candidates.map(sourceFromCandidate) }));
        setSelectionBasis(contactSelectionBasis(sceneRunId, sceneManifest, draft.simulation));
        requestId.current = null; setSubmitError(false);
      }} onAdd={staleSelection ? undefined : candidate => {
        setDraft(previous => ({ ...previous, source_cells: [...previous.source_cells, sourceFromCandidate(candidate)] }));
        setSelectionBasis(contactSelectionBasis(sceneRunId, sceneManifest, draft.simulation));
        requestId.current = null; setSubmitError(false);
      }} onAddMany={staleSelection ? undefined : candidates => {
        setDraft(previous => {
          const occupied = new Set([...previous.source_cells.map(cell => String(cell.body_id)), ...previous.replay_ids.map(String)]);
          const added = candidates.filter(candidate => {
            const id = String(candidate.body_id);
            if (occupied.has(id)) return false;
            occupied.add(id); return true;
          }).map(sourceFromCandidate);
          return { ...previous, source_cells: [...previous.source_cells, ...added] };
        });
        setSelectionBasis(contactSelectionBasis(sceneRunId, sceneManifest, draft.simulation));
        requestId.current = null; setSubmitError(false);
      }} />
      <Checkbox mt={3} size="sm" isChecked={draft.retain_currents === true} isDisabled={sending} onChange={event => {
        setDraft(previous => { const next = { ...previous }; if (event.target.checked) next.retain_currents = true; else delete next.retain_currents; return next; });
        requestId.current = null; setSubmitError(false);
      }}>Сохранить токи для быстрого изменения E1 и REF</Checkbox>
      <Text fontSize="11px" color={SIMULATION_THEME.textSecondary}>Дополнительный архив увеличит время и объём сохранения.</Text>
      <Checkbox mt={3} size="sm" isChecked={draft.retain_state_contrast === true} isDisabled={sending} onChange={event => {
        setDraft(previous => { const next = { ...previous }; if (event.target.checked) next.retain_state_contrast = true; else delete next.retain_state_contrast; return next; });
        requestId.current = null; setSubmitError(false);
      }}>Сохранить разность состояний сети</Checkbox>
      <Checkbox mt={3} size="sm" isChecked={draft.retain_compartment_crossings === true} isDisabled={sending} onChange={event => {
        setDraft(previous => { const next = { ...previous }; if (event.target.checked) next.retain_compartment_crossings = true; else delete next.retain_compartment_crossings; return next; });
        requestId.current = null; setSubmitError(false);
      }}>Показать переходы компартментов</Checkbox>
      <Text fontSize="11px" color={SIMULATION_THEME.textSecondary}>Дополнительная запись только для выбранных клеток; не спайки и не полная нейросеть.</Text>
      <Text fontSize="11px" color={SIMULATION_THEME.textSecondary}>Для сравнения с контролем без входа; длительные записи могут охватывать только часть клеток.</Text>
      {!validDraft && <Text role="alert" fontSize="12px" color="orange.200" mt={2}>Проверьте координаты, зазоры, состав клеток и параметры импульса и временной сетки.</Text>}
      {staleSelection && <Box mt={2}><Text role="alert" fontSize="12px" color="orange.200">Контакты изменились после выбора клеток. Повторите поиск или подтвердите прежний состав. Близость клеток к новым контактам не проверена.</Text>
        <Button type="button" size="xs" variant="outline" mt={1} onClick={() => setSelectionBasis(contactSelectionBasis(sceneRunId, sceneManifest, draft.simulation))}>Оставить прежний состав клеток</Button></Box>}
      {!fitsRequest && <Text role="alert" fontSize="12px" color="orange.200" mt={2}>Конфигурация превышает размер запроса. Сократите выбранный состав клеток.</Text>}
      {submitError && <Text role="alert" fontSize="12px" color="orange.200" mt={2}>{submitError === 'invalid' ? 'Параметры не прошли проверку сервиса. Измените положение контактов.' : submitError === 'conflict' ? 'Запрос конфликтует с предыдущим. Измените параметры перед повтором.' : 'Не удалось подтвердить отправку. Повтор использует тот же идентификатор запроса.'}</Text>}
      <HStack mt={3}><Button size="sm" type="submit" isDisabled={!validDraft || staleSelection || sending || submitError === 'invalid' || submitError === 'conflict'} isLoading={sending}>{submitError === 'uncertain' ? 'Повторить отправку' : 'Запустить расчёт'}</Button><Button size="sm" variant="ghost" isDisabled={sending} onClick={() => { setDraft(null); setSelectionBasis(null); requestId.current = null; }}>Отмена</Button></HStack>
    </Box>}
    {!preview && !state.items.some(item => active.has(item.state)) && <Text fontSize="12px" mt={2}>{newest?.state === 'failed' ? 'Последний расчёт завершился ошибкой.' : 'Завершённых записей нет.'}</Text>}
  </Box>;
}
