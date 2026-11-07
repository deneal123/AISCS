import React, { useEffect, useRef, useState } from 'react';
import { Box, Button, Checkbox, FormControl, FormLabel, Input, Select, Text } from '@chakra-ui/react';
import { simulationApi } from '../api';
import SignalPlot from './SignalPlot';
import VoltageProbePlot from './VoltageProbePlot';

const fields = [
  ['delay_ms', 'Задержка, мс'], ['weight_us', 'Проводимость, мкСм'],
  ['tau1_ms', 'Нарастание, мс'], ['tau2_ms', 'Спад, мс'],
  ['reversal_mv', 'Потенциал реверсии, мВ'], ['max_target_distance_um', 'Допуск геометрии, мкм'],
];
const active = new Set(['queued', 'preparing', 'running', 'publishing', 'cancelling']);
const matchesTarget = (run, sourceId, nodeId, expectedId) => Boolean(run?.id)
  && (!expectedId || run.id === expectedId) && run.parent_run_id === sourceId
  && String(run.configuration?.target_id) === String(nodeId);

export default function PopulationTargetReplay({ runId, nodeId, candidates, onShowOnTimeline, onFocusProbe, morphologyHash }) {
  const [selected, setSelected] = useState([]);
  const [timingMode, setTimingMode] = useState('tick');
  const [values, setValues] = useState(Object.fromEntries(fields.map(([key]) => [key, ''])));
  const [run, setRun] = useState(null);
  const [history, setHistory] = useState([]);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const [time, setTime] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [loadFailed, setLoadFailed] = useState(false);
  const requestId = useRef(null);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setLoadFailed(false);
    (async () => {
      try {
        const result = await simulationApi.populationTargetRuns(runId, nodeId, controller.signal);
        const latest = result.items?.find(item => active.has(item.state))
          || result.items?.find(item => item.state === 'completed') || result.items?.[0];
        const restored = latest ? await simulationApi.get(latest.id, controller.signal) : null;
        if (restored && !matchesTarget(restored, runId, nodeId, latest.id)) throw new Error('source_mismatch');
        if (!controller.signal.aborted) { setHistory(result.items || []); setRun(restored); setLoading(false); }
      } catch {
        if (!controller.signal.aborted) { setLoading(false); setLoadFailed(true); setError('Не удалось загрузить сохранённые расчёты.'); }
      }
    })();
    return () => controller.abort();
  }, [runId, nodeId, loadAttempt]);
  useEffect(() => {
    if (!run?.id || !active.has(run.state)) return undefined;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      simulationApi.get(run.id, controller.signal).then(next => {
        if (!matchesTarget(next, runId, nodeId, run.id)) throw new Error('source_mismatch');
        if (!controller.signal.aborted) setRun(next);
    }).catch(() => { if (!controller.signal.aborted) setError('Не удалось обновить состояние расчёта.'); });
    }, 5000);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [run, runId, nodeId]);
  const numbers = Object.fromEntries(fields.map(([key]) => [key, values[key].trim() === '' ? NaN : Number(values[key])]));
  const valid = Number.isSafeInteger(Number(nodeId)) && selected.length > 0
    && fields.every(([key]) => Number.isFinite(numbers[key]))
    && numbers.delay_ms >= 0 && numbers.weight_us > 0 && numbers.tau1_ms > 0
    && numbers.tau2_ms > numbers.tau1_ms && numbers.tau1_ms / numbers.tau2_ms >= 1e-9
    && numbers.tau1_ms / numbers.tau2_ms <= .9999 && numbers.max_target_distance_um >= 0;
  const locked = loading || loadFailed || sending || (run && active.has(run.state));
  const intervalsAvailable = selected.length > 0 && selected.every(id =>
    candidates.some(item => item.source_id === id && item.intervals_available === true));
  const change = (key, value) => { requestId.current = null; setValues(previous => ({ ...previous, [key]: value })); };
  const start = async () => {
    if (!valid || locked) return;
    setError(''); setSending(true);
    try {
      const source = await simulationApi.preparePopulationTarget(runId);
      if (!mounted.current) return;
      if (!Array.isArray(source.source_ids) || selected.some(id => !source.source_ids.includes(id))) throw new Error('source_changed');
      requestId.current ||= crypto.randomUUID();
      const { max_target_distance_um, ...synapse } = numbers;
      const created = await simulationApi.createPopulationTarget({
        request_id: requestId.current, parent_run_id: runId, title: `Целевой нейрон ${nodeId}`,
        configuration: { graph_manifest_sha256: source.graph_manifest_sha256, source_package_sha256: source.sha256,
          source_manifest_sha256: source.manifest_sha256, target_id: Number(nodeId), source_ids: selected,
          synapses: selected.map(() => ({ ...synapse })), duration_ms: source.duration_ms,
          max_target_distance_um, max_events: 1000000,
          ...(timingMode !== 'tick' ? { timing_mode: timingMode } : {}) },
      });
      if (!matchesTarget(created, runId, nodeId)) throw new Error('source_mismatch');
      if (mounted.current) {
        setHistory(previous => [created, ...previous.filter(item => item.id !== created.id)].slice(0, 30));
        setRun(created); requestId.current = null;
      }
    } catch {
      if (mounted.current) setError('Не удалось запустить расчёт. Проверьте параметры и доступность исходной записи.');
    } finally { if (mounted.current) setSending(false); }
  };
  const selectSaved = async id => {
    setLoading(true); setError('');
    try {
      const saved = await simulationApi.get(id);
      if (!matchesTarget(saved, runId, nodeId, id)) throw new Error('source_mismatch');
      if (mounted.current) { setRun(saved); setTime(0); }
    } catch {
      if (mounted.current) setError('Не удалось открыть выбранный расчёт.');
    } finally { if (mounted.current) setLoading(false); }
  };
  const preview = run?.result?.preview;
  return <Box as="details" mt={2}>
    <Text as="summary" cursor="pointer">Рассчитать ответ нейрона</Text>
    {loading && <Text role="status">Поиск сохранённого расчёта…</Text>}
    {history.length > 1 && <FormControl mt={2}>
      <FormLabel fontSize="11px" mb={0}>Сохранённый расчёт</FormLabel>
      <Select size="xs" value={run?.id || ''} isDisabled={Boolean(locked)} onChange={event => selectSaved(event.target.value)}>
        {history.map(item => <option key={item.id} value={item.id}>{item.configuration?.timing_mode === 'lower_bound' ? 'Нижняя граница' : item.configuration?.timing_mode === 'upper_bound' ? 'Верхняя граница' : 'Тик графа'} · {item.created_at ? new Date(item.created_at).toLocaleString('ru-RU') : item.id.slice(0, 8)}</option>)}
      </Select>
    </FormControl>}
    <Text color="gray.400" mt={2}>Односторонний повтор: параметры синапсов задаются исследователем и не откалиброваны. События графа округлены вперёд до шага 1 мс.</Text>
    {['upper_bound', 'lower_bound'].map(mode => <Checkbox key={mode} mt={2} display="block" size="sm"
      isChecked={timingMode === mode && intervalsAvailable} isDisabled={locked || !intervalsAvailable}
      onChange={event => { requestId.current = null; setTimingMode(event.target.checked ? mode : 'tick'); }}>
      Повтор по {mode === 'upper_bound' ? 'верхней' : 'нижней'} границе интервала
    </Checkbox>)}
    {selected.length > 0 && !intervalsAvailable && <Text fontSize="10px" color="gray.400">Для выбранных источников интервалы отсутствуют. Доступен повтор по тикам графа.</Text>}
    {timingMode !== 'tick' && <Text fontSize="10px" color="gray.400">Только для записей с сохранёнными интервалами; сеть LIF сохраняет шаг 1 мс. Границы не являются точным моментом пересечения.</Text>}
    {candidates.map(item => <Checkbox key={item.source_id} display="block" size="sm" isDisabled={locked}
      isChecked={selected.includes(item.source_id)} onChange={event => {
        requestId.current = null;
        setTimingMode('tick');
        setSelected(previous => event.target.checked ? [...previous, item.source_id] : previous.filter(id => id !== item.source_id));
      }}>{item.source_id} · событий: {item.events}</Checkbox>)}
    {fields.map(([key, label]) => <FormControl key={key} mt={2}>
      <FormLabel fontSize="11px" mb={0}>{label}</FormLabel>
      <Input size="xs" type="number" value={values[key]} isDisabled={locked} onChange={event => change(key, event.target.value)} />
    </FormControl>)}
    <Button size="xs" mt={2} isLoading={sending} isDisabled={!valid || locked} onClick={start}>Рассчитать</Button>
    {error && <Box mt={2}><Text role="alert" color="orange.200">{error}</Text>
      {loadFailed && <Button size="xs" onClick={() => { setError(''); setLoadAttempt(value => value + 1); }}>Повторить загрузку</Button>}
      {run && active.has(run.state) && <Button size="xs" onClick={async () => {
        try { const next = await simulationApi.get(run.id);
          if (!matchesTarget(next, runId, nodeId, run.id)) throw new Error('source_mismatch');
          if (mounted.current) { setError(''); setRun(next); } }
        catch { if (mounted.current) setError('Не удалось обновить состояние расчёта.'); }
      }}>Обновить состояние</Button>}
    </Box>}
    {run && <Text role="status" mt={2}>Состояние: {run.state === 'completed' ? 'завершён' : run.state === 'failed' ? 'ошибка' : run.state === 'cancelled' ? 'остановлен' : 'расчёт'}</Text>}
    {run?.state === 'failed' && <Text color="orange.200">Проверка или расчёт не выполнены. Проверьте параметры и совместимость морфологии.</Text>}
    {preview && <Box mt={2}>
      <Text>E1 − REF · {preview.source_cells} исходных клеток + цель {preview.target_id}</Text>
      <Text color="gray.400">{preview.timing_mode === 'upper_bound' ? 'Время событий: верхняя граница интервала.' : preview.timing_mode === 'lower_bound' ? 'Время событий: нижняя граница интервала.' : 'Время событий: тик графа 1 мс.'}</Text>
      <SignalPlot preview={{ time_ms: preview.time_ms, signal_uv: preview.neural_uv }} timeMs={time} onTime={setTime} />
      <VoltageProbePlot preview={preview} timeMs={time} />
      <Text color="gray.400">Сигнал без артефакта стимуляции; без обратного влияния цели на сеть.</Text>
      {onShowOnTimeline && <Button size="xs" variant="outline" mt={2} onClick={() => onShowOnTimeline(run)}>Показать на общей шкале</Button>}
      {onFocusProbe && preview.probe_morphology_sha256 && <Button size="xs" variant="outline" mt={2}
        isDisabled={morphologyHash !== preview.probe_morphology_sha256}
        onClick={() => { onShowOnTimeline?.(run); onFocusProbe(preview); }}>Приблизить компартмент</Button>}
    </Box>}
  </Box>;
}
