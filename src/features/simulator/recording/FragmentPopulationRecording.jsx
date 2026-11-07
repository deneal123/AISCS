import React, { useCallback, useEffect, useRef, useState } from 'react';
import { executorStartError } from '../executorStartError';
import { Box, FormControl, FormLabel, Input, Text } from '@chakra-ui/react';
import { simulationApi } from '../api';
import { fieldDemoPreset } from '../field/fieldDemoPreset';
import { contactSelectionBasis as contactBasis } from '../field/contactSelectionBasis';
import { candidateEligibility } from '../field/fieldCandidateEligibility';
import { SIMULATION_THEME } from '../theme';
import usePopulationFeedback from './usePopulationFeedback';
import useWholeNetworkProxy from './useWholeNetworkProxy';
import useDirectNetworkProxy from './useDirectNetworkProxy';
import AppSelect from '@shared/controls/AppSelect';
import { validFeedbackDuration } from '../feedbackDuration';
import { clearPendingFeedback, readPendingFeedback, readSelectedFeedbackSource,
  writePendingFeedback, writeSelectedFeedbackSource } from './pendingFeedbackStorage';

const active = new Set(['queued', 'preparing', 'running', 'publishing', 'cancelling']);
const contacts = [['source_um', 'STIM+'], ['return_um', 'STIM−'], ['electrode_um', 'E1'], ['reference_um', 'REF']];
const tabStorage = () => { try { return window.sessionStorage; } catch { return null; } };

export default function FragmentPopulationRecording({ sceneRunId, sceneManifest, onShowOnBody, canRestore, incomingContacts, onConsumeContacts, onAdjustContact, formRef, onPrimaryStatus, onClearanceNotice, onFailure }) {
  const preset = fieldDemoPreset(sceneManifest);
  const [ids, setIds] = useState('174827, 176609');
  const [excludedIds, setExcludedIds] = useState([]);
  const [searchRadius, setSearchRadius] = useState('10');
  const [calculationMode, setCalculationMode] = useState('detailed');
  const direct = useDirectNetworkProxy((run, simulation) => {
    if (simulation) onShowOnBody?.(run, { direct: true, simulation });
  }, sceneRunId);
  const [, setSelectionBasis] = useState(null);
  const [coordinates, setCoordinates] = useState({
    source_um: [429.056, 387.68, 228.352], return_um: [929.056, 327.68, 228.352],
    electrode_um: [419.328, 379.488, 359.92], reference_um: [919.328, 319.488, 359.92],
  });
  const [state, setState] = useState({ items: [], selected: null, loading: true, error: false });
  const [retry, setRetry] = useState(0);
  const [sending, setSending] = useState(false);
  const [preparationStage, setPreparationStage] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [sourceProgress, setSourceProgress] = useState(null);
  const cancelRef = useRef(null);
  const cancelAction = useCallback(() => cancelRef.current?.(), []);
  const [submitError, setSubmitError] = useState('');
  const [clearanceNotice, setClearanceNotice] = useState('');
  useEffect(() => { onClearanceNotice?.(clearanceNotice); }, [clearanceNotice, onClearanceNotice]);
  const [baseConfiguration, setBaseConfiguration] = useState(null);
  const [pendingFeedback, setPendingFeedback] = useState(null);
  const [feedbackRequestId, setFeedbackRequestId] = useState(null);
  const [feedbackRetryReceipt, setFeedbackRetryReceipt] = useState(false);
  const requestId = useRef(null);
  const preparationRequest = useRef(null);
  const selectedRunId = useRef(null);
  const autoShowRunId = useRef(null);
  const restoredScene = useRef(null);
  const onShowOnBodyRef = useRef(onShowOnBody); onShowOnBodyRef.current = onShowOnBody;
  const reportedFeedbackFailure = useRef(null);
  const feedback = usePopulationFeedback(state.selected, state.selected?.id === pendingFeedback, feedbackRequestId,
    feedbackRetryReceipt, ({ sourceId, requestId: retryRequestId }) => {
      writePendingFeedback(tabStorage(), sceneRunId, { version: 1, sourceId, requestId: retryRequestId, retry: true });
      reportedFeedbackFailure.current = null;
      setFeedbackRequestId(retryRequestId); setFeedbackRetryReceipt(true); setPendingFeedback(sourceId);
    });
  const proxy = useWholeNetworkProxy(state.selected, feedback.status === 'completed',
    state.selected?.id === pendingFeedback);
  const shownFeedback = useRef(null);
  const reportedProxyFailure = useRef(null);
  const onFailureRef = useRef(onFailure); onFailureRef.current = onFailure;
  useEffect(() => {
    if (!['error', 'failed'].includes(feedback.status) || !pendingFeedback
        || feedback.sourceId !== pendingFeedback || reportedFeedbackFailure.current === pendingFeedback) return;
    reportedFeedbackFailure.current = pendingFeedback;
    onFailureRef.current?.();
  }, [feedback.status, feedback.sourceId, pendingFeedback]);
  useEffect(() => {
    if (feedback.status !== 'completed' || !feedback.run || !state.selected
        || (state.selected.id === pendingFeedback && ['idle', 'loading', ...active].includes(proxy.status))) return;
    const shownKey = `${feedback.run.id}:${proxy.status === 'completed' ? proxy.run?.id : 'coupled'}`;
    if (shownFeedback.current === shownKey) return;
    const restore = state.selected.id !== pendingFeedback && state.selected.id !== autoShowRunId.current;
    if (restore && canRestore && !canRestore()) return;
    const configuration = state.selected.configuration, simulation = configuration?.simulation;
    if (configuration?.graph_manifest_sha256 !== sceneManifest || !Array.isArray(configuration.source_ids)
        || !contacts.every(([key]) => Array.isArray(simulation?.[key]) && simulation[key].length === 3
          && simulation[key].every(Number.isFinite))) return;
    setBaseConfiguration(configuration);
    setCoordinates(Object.fromEntries(contacts.map(([key]) => [key, [...simulation[key]]])));
    setIds(configuration.source_ids.join(', ')); setExcludedIds([]);
    setSelectionBasis(contactBasis(sceneRunId, sceneManifest, simulation));
    shownFeedback.current = shownKey;
    writeSelectedFeedbackSource(tabStorage(), sceneRunId, state.selected.id);
    onShowOnBodyRef.current?.(feedback.run, { source: state.selected, restore,
      ...(proxy.status === 'completed' ? { proxy: proxy.run } : {}) });
    restoredScene.current = sceneRunId;
    if (!restore) autoShowRunId.current = null;
  }, [feedback.status, feedback.run, state.selected, pendingFeedback, sceneRunId, sceneManifest, canRestore, proxy.status, proxy.run]);
  useEffect(() => {
    const sourceId = state.selected?.id;
    if (!sourceId || sourceId !== pendingFeedback || feedback.status !== 'completed'
        || !['error', 'failed', 'cancelled', 'unavailable'].includes(proxy.status)
        || reportedProxyFailure.current === sourceId) return;
    reportedProxyFailure.current = sourceId;
    onFailureRef.current?.();
  }, [state.selected?.id, pendingFeedback, feedback.status, proxy.status]);
  useEffect(() => { setBaseConfiguration(null); }, [sceneManifest]);
  useEffect(() => {
    const receipt = readPendingFeedback(tabStorage(), sceneRunId);
    restoredScene.current = null;
    selectedRunId.current = receipt?.sourceId || readSelectedFeedbackSource(tabStorage(), sceneRunId);
    autoShowRunId.current = receipt?.sourceId || null;
    setPendingFeedback(receipt?.sourceId || null); setFeedbackRequestId(receipt?.requestId || null);
    setFeedbackRetryReceipt(receipt?.retry === true);
  }, [sceneRunId]);
  useEffect(() => {
    const feedbackEnded = ['failed', 'cancelled'].includes(feedback.status);
    const proxyEnded = feedback.status === 'completed'
      && ['completed', 'failed', 'cancelled', 'error', 'unavailable'].includes(proxy.status);
    if (pendingFeedback && feedback.sourceId === pendingFeedback && (feedbackEnded || proxyEnded)) {
      clearPendingFeedback(tabStorage(), sceneRunId, pendingFeedback);
    }
  }, [feedback.sourceId, feedback.status, proxy.status, pendingFeedback, sceneRunId]);
  useEffect(() => {
    if (!incomingContacts || incomingContacts.kind !== 'fragments') return;
    const config = incomingContacts.configuration, simulation = incomingContacts.simulation;
    if (config?.graph_manifest_sha256 !== sceneManifest || !Array.isArray(config.source_ids)
        || !contacts.every(([key]) => Array.isArray(simulation?.[key]) && simulation[key].length === 3
          && simulation[key].every(Number.isFinite))) {
      setSubmitError('Не удалось перенести контакты: проверьте совместимость графа и координат.');
      onConsumeContacts?.(); return;
    }
    setBaseConfiguration(config);
    setIds(config.source_ids.join(', '));
    setExcludedIds([]);
    // Preset IDs are only placeholders, not a spatial selection. A fresh
    // scene must resolve the population even if its contacts did not move.
    setSelectionBasis(incomingContacts.fieldRunId ? contactBasis(sceneRunId, sceneManifest, config.simulation) : 'unverified');
    setCoordinates(Object.fromEntries(contacts.map(([key]) => [key, [...simulation[key]]])));
    requestId.current = null; setSubmitError(''); onConsumeContacts?.();
  }, [incomingContacts, onConsumeContacts, sceneManifest, sceneRunId]);
  useEffect(() => {
    const controller = new AbortController();
    let timer;
    async function load() {
      try {
        const response = await simulationApi.fragmentPopulationRuns(controller.signal, sceneRunId);
        if (!Array.isArray(response?.items)) throw new Error('invalid_population_list');
        const items = [...response.items];
        let preferred = items.find(item => item.id === selectedRunId.current);
        let selected = null;
        if (!preferred && selectedRunId.current) {
          const restored = await simulationApi.get(selectedRunId.current, controller.signal);
          if (restored?.id !== selectedRunId.current || restored.parent_run_id !== sceneRunId
              || !Array.isArray(restored.configuration?.source_ids)
              || (sceneManifest && restored.configuration?.graph_manifest_sha256 !== sceneManifest)) {
            throw new Error('invalid_saved_population');
          }
          preferred = restored;
          items.push(restored);
          if (restored.state === 'completed') selected = restored;
        }
        const completed = preferred ? (preferred.state === 'completed' ? preferred : null)
          : items.find(item => item.state === 'completed');
        if (completed && !selected) selected = await simulationApi.get(completed.id, controller.signal);
        if (controller.signal.aborted) return;
        setState({ items, selected, loading: false, error: false });
        if (items.some(item => active.has(item.state))) timer = setTimeout(load, 10000);
      } catch (error) {
        if (!controller.signal.aborted) setState(previous => ({ ...previous, loading: false, error: true }));
      }
    }
    load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [retry, sceneRunId, sceneManifest]);
  const activeSourceId = state.items.find(item => item.id === pendingFeedback && active.has(item.state))?.id;
  useEffect(() => {
    if (!activeSourceId) return undefined;
    let socket, reconnectTimer, disposed = false, lastSnapshot = null;
    setSourceProgress(null);
    const connect = () => {
      if (disposed) return;
      try { socket = new WebSocket(simulationApi.eventsUrl(activeSourceId)); } catch { return; }
      socket.onmessage = message => {
        try {
          const payload = JSON.parse(message.data);
          if (payload.type === 'snapshot' && payload.run?.id === activeSourceId) {
            const version = payload.run.state;
            if (version !== lastSnapshot) { lastSnapshot = version; setRetry(value => value + 1); }
          } else if (payload.event?.run_id === activeSourceId) {
            const progress = payload.event.progress;
            if (progress && ['geometry', 'cells', 'network'].includes(progress.phase)
                && Number.isInteger(progress.done) && Number.isInteger(progress.total)
                && ((progress.phase === 'network' && progress.done === 0 && progress.total === 0)
                  || (progress.phase !== 'network' && progress.done > 0 && progress.done <= progress.total && progress.total <= 256))) {
              setSourceProgress({ ...progress, runId: activeSourceId });
            } else setRetry(value => value + 1);
          }
        } catch { /* The periodic HTTP refresh remains authoritative. */ }
      };
      socket.onclose = () => { if (!disposed) reconnectTimer = setTimeout(connect, 2000); };
    };
    connect();
    return () => { disposed = true; clearTimeout(reconnectTimer); socket?.close?.(); };
  }, [activeSourceId]);
  const idsList = ids.split(',').map(value => value.trim());
  const validIds = idsList.length > 0 && idsList.length <= 256 && idsList.every(value => /^[1-9]\d*$/.test(value) && Number.isSafeInteger(Number(value))) && new Set(idsList).size === idsList.length;
  const validCoordinates = contacts.every(([key]) => coordinates[key].every(value => String(value).trim() !== '' && Number.isFinite(Number(value))));
  const stimulusCurrent = baseConfiguration?.simulation?.current_na ?? preset?.simulation?.current_na ?? '';
  const simulationSettings = baseConfiguration?.simulation || preset?.simulation;
  const duration = simulationSettings?.duration_ms ?? '';
  const validCurrent = String(stimulusCurrent).trim() !== '' && Number.isFinite(Number(stimulusCurrent));
  const validDuration = validFeedbackDuration(simulationSettings, duration);
  const validSearchRadius = searchRadius.trim() !== '' && Number.isFinite(Number(searchRadius)) && Number(searchRadius) >= 0;
  const draftSignature = JSON.stringify([sceneRunId, sceneManifest, coordinates, stimulusCurrent, duration, ids, searchRadius]);
  const latestDraft = useRef(draftSignature); latestDraft.current = draftSignature;
  const running = state.items.some(item => active.has(item.state));
  const primaryReady = Boolean(preset && sceneRunId && (calculationMode === 'fast' || validIds) && validCoordinates && validCurrent && validDuration && (calculationMode === 'fast' || validSearchRadius) && !sending && !running && !state.loading && !state.error);
  const feedbackRunning = ['loading', 'queued', 'preparing', 'running', 'publishing', 'cancelling'].includes(feedback.status);
  const proxyRunning = feedback.status === 'completed' && state.selected?.id === pendingFeedback
    && ['idle', 'loading', 'queued', 'preparing', 'running', 'publishing', 'cancelling'].includes(proxy.status);
  useEffect(() => {
    const inProgress = running || sending || feedbackRunning || proxyRunning || direct.running;
    const sourceState = state.items.find(item => item.id === pendingFeedback)?.state;
    const stage = sending ? (preparationStage || 'Проверка контактов') : running
      ? ({ queued: 'Ожидание запуска', preparing: 'Подготовка модели', running: 'Расчёт нейронов', publishing: 'Сохранение записи', cancelling: 'Остановка' }[sourceState] || 'Расчёт нейронов')
      : feedbackRunning ? ({ queued: 'Ожидание расчёта сети', preparing: 'Подготовка сети', running: 'Расчёт сети', publishing: 'Сохранение ответа', cancelling: 'Остановка' }[feedback.status] || 'Подготовка сети')
      : proxyRunning || direct.running ? 'Модель всей сети ЦНС' : null;
    onPrimaryStatus?.({ ready: primaryReady && !feedbackRunning && !proxyRunning && !direct.running, running: inProgress,
      ...(stage ? { stage, phase: sending ? 0 : running ? 1 : 2,
        canCancel: !cancelling && (Boolean(direct.run?.id && direct.running) || (sending && !submitting) || Boolean(state.items.find(item => item.id === pendingFeedback && active.has(item.state))) || Boolean(feedback.run && active.has(feedback.status)) || Boolean(proxy.run && active.has(proxy.status))),
        progress: running && sourceProgress?.runId === pendingFeedback ? sourceProgress
          : feedbackRunning ? feedback.progress : proxyRunning ? proxy.progress : direct.running ? direct.progress : null,
        connectionLost: Boolean((feedbackRunning && feedback.connectionLost) || (proxyRunning && proxy.connectionLost)),
        cancel: cancelAction } : {}) });
  }, [onPrimaryStatus, primaryReady, running, sending, preparationStage, submitting, feedbackRunning, feedback.status, feedback.run, feedback.progress, feedback.connectionLost, proxyRunning, proxy.status, proxy.run, proxy.progress, proxy.connectionLost, direct.running, direct.progress, direct.run?.id, state.items, pendingFeedback, cancelling, cancelAction, sourceProgress]);
  const submit = async event => {
    event.preventDefault();
    if (!preset || (calculationMode !== 'fast' && !validIds) || !validCoordinates || !validCurrent || !validDuration || (calculationMode !== 'fast' && !validSearchRadius) || sending || running || feedbackRunning || proxyRunning || direct.running || state.loading || state.error) return;
    const original = baseConfiguration || { graph_manifest_sha256: sceneManifest, source_ids: [], seed: 1,
      simulation: preset.simulation, threshold_mv: -20, max_distance_um: 2 };
    const simulation = { ...original.simulation, ...Object.fromEntries(contacts.map(([key]) => [key, coordinates[key].map(Number)])), allow_disconnected: true };
    if (calculationMode === 'fast') {
      await direct.start(sceneRunId, { request_id: crypto.randomUUID(), simulation,
        graph_manifest_sha256: sceneManifest, seed: original.seed, gain: 1000000,
        allow_partial_geometry: true, allow_missing_curvature: true, allow_contact_exclusion: false });
      return;
    }
    let submitted = false;
    const preparation = new AbortController(); preparationRequest.current = preparation;
    setPreparationStage('Проверка контактов'); setSending(true); setSubmitError(''); setClearanceNotice('');
    try {
      if (sceneRunId) {
        const screen = await simulationApi.contactScreen(sceneRunId, {
          ...Object.fromEntries(contacts.map(([key]) => [key, simulation[key]])), clearance_um: simulation.clearance_um,
        }, preparation.signal);
        if (latestDraft.current !== draftSignature) {
          setSubmitError('Положение или параметры изменились во время проверки. Запустите расчёт снова.'); onFailure?.(); return;
        }
        if (!Array.isArray(screen?.potential_intersections)) throw new Error('invalid_contact_screen');
        if (screen.potential_intersections.length) {
          const indices = new Set(screen.potential_intersections.flatMap(row => row.contact_indices || []));
          if ([...indices].some(index => !Number.isInteger(index) || index < 0 || index >= contacts.length))
            throw new Error('invalid_contact_screen');
          const names = [...indices].sort((a, b) => a - b).map(index => contacts[index][1]).join(', ');
          setSubmitError(`Контакты ${names || 'электродов'} слишком близко к отросткам. Переместите их и повторите запуск.`);
          onFailure?.(); return;
        }
      }
      let sourceIds = idsList.map(Number);
      let selectionRadius = null;
      if (sceneRunId) {
        let radius = Number(searchRadius), eligible = [], cachedSearch = null;
        // The executor accepts at most 256 sources. Repeat the complete spatial
        // query at a smaller explicit radius; never silently truncate its rows.
        for (let attempt = 0; attempt < 8; attempt += 1) {
          setPreparationStage(`Поиск нейронов · попытка ${attempt + 1} из 8`);
          const queryRadius = radius;
          // A complete larger-radius result can answer a narrower query exactly.
          // Unknown distances or a larger radius must go back to the server.
          const reusable = cachedSearch && queryRadius <= cachedSearch.radius
            && cachedSearch.candidates.every(row => Number.isFinite(row.distance_um) && row.distance_um >= 0);
          const result = reusable
            ? { candidates: cachedSearch.candidates.filter(row => row.distance_um <= queryRadius) }
            : await simulationApi.spatialCandidates(sceneRunId, {
              ...Object.fromEntries(contacts.map(([key]) => [key, simulation[key]])), radius_um: queryRadius,
            }, preparation.signal);
          if (preparation.signal.aborted) return;
          if (latestDraft.current !== draftSignature) {
            setSubmitError('Положение или параметры изменились во время поиска. Запустите расчёт снова.'); onFailure?.(); return;
          }
          if (!Array.isArray(result?.candidates)) throw new Error('invalid_candidates');
          if (!reusable) cachedSearch = { radius: queryRadius, candidates: result.candidates };
          eligible = result.candidates.filter(row => !candidateEligibility(row, simulation).unavailable);
          if (eligible.length > 0 && eligible.length <= 256) break;
          if (!eligible.length && radius < 200) radius = Math.min(radius > 0 ? radius * 2 : 5, 200);
          else if (eligible.length > 256) radius /= 2;
          else break;
        }
        if (!eligible.length || eligible.length > 256) {
          setSubmitError(!eligible.length ? 'Рядом с контактами не найдены подходящие реконструкции. Измените положение или настройте поиск.'
            : 'Слишком много подходящих клеток даже после уменьшения радиуса поиска.'); onFailure?.(); return;
        }
        sourceIds = eligible.map(row => row.body_id);
        selectionRadius = radius;
      }
      requestId.current ||= crypto.randomUUID();
      const scope = selectionRadius === null ? `STIM: выбранные клетки (${sourceIds.length})` : `STIM: радиус ${selectionRadius} мкм, клеток ${sourceIds.length}`;
      const title = selectionRadius === null && excludedIds.length ? `${scope}, исключено ${excludedIds.length}` : scope;
      const submittedConfiguration = {
        ...original, graph_manifest_sha256: sceneManifest, source_ids: sourceIds, simulation,
        allow_partial_geometry: true,
      };
      if (preparation.signal.aborted) return;
      preparationRequest.current = null; setPreparationStage('Постановка расчёта'); setSubmitting(true);
      const created = await simulationApi.createFragmentPopulation({ request_id: requestId.current, parent_run_id: sceneRunId || null, title, configuration: submittedConfiguration });
      const resumeRequest = crypto.randomUUID();
      writePendingFeedback(tabStorage(), sceneRunId, { version: 1, sourceId: created.id, requestId: resumeRequest });
      if (latestDraft.current !== draftSignature) {
        setState(previous => ({ ...previous, items: [created, ...previous.items.filter(item => item.id !== created.id)] }));
        requestId.current = null; setRetry(value => value + 1);
        setSubmitError('Расчёт запущен с прежними параметрами; изменённое положение сохранено как черновик.');
        onFailure?.(); return;
      }
      if (selectionRadius !== null) {
        setSearchRadius(String(selectionRadius)); setIds(sourceIds.join(', ')); setExcludedIds([]);
        setSelectionBasis(contactBasis(sceneRunId, sceneManifest, simulation));
      }
      setCoordinates(Object.fromEntries(contacts.map(([key]) => [key, [...simulation[key]]])));
      onAdjustContact?.({ kind: 'fragments', configuration: submittedConfiguration, simulation }, null);
      setState(previous => ({ ...previous, items: [created, ...previous.items.filter(item => item.id !== created.id)] }));
      requestId.current = null; selectedRunId.current = created.id; autoShowRunId.current = created.id; setFeedbackRequestId(resumeRequest); setFeedbackRetryReceipt(false); setPendingFeedback(created.id); setRetry(value => value + 1);
      submitted = true;
    } catch (error) {
      if (preparation.signal.aborted) { setClearanceNotice(''); return; }
      const status = error?.status ?? error?.response?.status;
      setClearanceNotice('');
      setSubmitError(error?.message === 'contact_draft_changed' ? 'Положение или параметры изменились во время проверки. Запустите расчёт снова.'
        : status === 422 ? 'Проверьте идентификаторы и параметры.'
        : status === 429 ? 'Проверка геометрии занята другим запросом. Дождитесь её завершения и повторите запуск.'
          : status === 503 ? 'Проверка геометрии временно недоступна. Повторите запуск позже.'
            : 'Не удалось подтвердить запуск. Повторите запрос.');
      onFailure?.();
    } finally { if (preparationRequest.current === preparation) preparationRequest.current = null; if (!submitted) setClearanceNotice(''); setSubmitting(false); setSending(false); setPreparationStage(null); }
  };
  const newest = state.items[0];
  const reportedSourceFailure = useRef(null);
  useEffect(() => {
    if (newest?.state !== 'failed' || newest.id !== pendingFeedback
        || reportedSourceFailure.current === newest.id) return;
    reportedSourceFailure.current = newest.id;
    onFailureRef.current?.();
  }, [newest?.state, newest?.id, pendingFeedback]);
  useEffect(() => {
    if (!pendingFeedback || !state.items.some(item => item.id === pendingFeedback
        && ['failed', 'cancelled'].includes(item.state))) return;
    clearPendingFeedback(tabStorage(), sceneRunId, pendingFeedback);
    setPendingFeedback(null); setFeedbackRequestId(null); setFeedbackRetryReceipt(false);
  }, [pendingFeedback, sceneRunId, state.items]);
  const geometryFailure = /^executor_synapse_geometry:([1-9]\d*):([1-9]\d*):([1-9]\d*)$/.exec(newest?.error || '');
  const geometryFailures = /^executor_synapse_geometries:([\d:,]+);omitted:(\d+)$/.exec(newest?.error || '');
  const cancel = async () => {
    if (direct.running) { await direct.cancel(); return; }
    if (sending && preparationRequest.current) { preparationRequest.current.abort(); return; }
    const target = proxy.run && active.has(proxy.status) ? proxy.run
      : feedback.run && active.has(feedback.status) ? feedback.run
      : state.items.find(item => item.id === pendingFeedback && active.has(item.state));
    if (!target || cancelling) return;
    setCancelling(true); setSubmitError('');
    try { await simulationApi.cancel(target.id); setRetry(value => value + 1); }
    catch { setSubmitError('Не удалось остановить расчёт. Повторите попытку.'); }
    finally { setCancelling(false); }
  };
  cancelRef.current = cancel;
  return <Box as="section" aria-label="STIM: выбранные клетки" borderTop="1px solid" borderColor={SIMULATION_THEME.panelBorder} pt={4}>
    <Text fontSize="14px" fontWeight="600">Параметры воздействия</Text>
    {!preset && <Text fontSize="12px">Для запуска откройте совместимую модель коннектома.</Text>}
    <Box as="form" ref={formRef} onSubmit={submit} mt={3}>
      <FormControl maxW="200px" mb={3}>
        <FormLabel fontSize="12px">Режим расчёта</FormLabel>
        <AppSelect ariaLabel="Режим расчёта" value={calculationMode} onChange={setCalculationMode}
          isDisabled={running || sending || feedbackRunning || proxyRunning || direct.running}
          options={[{ value: 'detailed', label: 'Подробный' }, { value: 'fast', label: 'Быстрый' }]} />
        {calculationMode === 'fast' && <Text fontSize="11px" color={SIMULATION_THEME.textSecondary}>Упрощённая сеть; запись E1–REF не рассчитывается.</Text>}
      </FormControl>
      <FormControl maxW="200px" isInvalid={!validCurrent}>
        <FormLabel fontSize="12px">Ток STIM, нА</FormLabel>
        <Input size="sm" type="number" isDisabled={!preset || running || sending || feedbackRunning} value={stimulusCurrent} onChange={event => {
          const value = event.target.value;
          setBaseConfiguration(previous => {
            const original = previous || { graph_manifest_sha256: sceneManifest, source_ids: [], seed: 1,
              simulation: preset.simulation, threshold_mv: -20, max_distance_um: 2 };
            return { ...original, simulation: { ...original.simulation, current_na: value === '' ? '' : Number(value) } };
          });
          requestId.current = null;
        }} />
        {validCurrent && Number(stimulusCurrent) === 0 && <Text fontSize="11px" color={SIMULATION_THEME.textSecondary} mt={1}>Контроль без электрического воздействия; остальные параметры сохраняются.</Text>}
      </FormControl>
      {calculationMode === 'detailed' && <FormControl maxW="200px" mt={3} isInvalid={!validSearchRadius}>
        <FormLabel fontSize="12px">Радиус поиска, мкм</FormLabel>
        <Input size="sm" type="number" min={0} isDisabled={running || sending || feedbackRunning} value={searchRadius} onChange={event => { setSearchRadius(event.target.value); setSelectionBasis('radius-changed'); requestId.current = null; }} />
      </FormControl>}
    </Box>
    {submitError && <Text role="alert" fontSize="12px" color="orange.200" mt={2}>{submitError}</Text>}
    {['error', 'failed'].includes(direct.status) && <Text role="alert" fontSize="12px" color="orange.200" mt={2}>{executorStartError(direct.run?.error) || 'Быстрый расчёт не завершён. Проверьте параметры и состояние сервиса.'}</Text>}
    {clearanceNotice && <Text role="status" fontSize="12px" color={SIMULATION_THEME.textSecondary} mt={2}>{clearanceNotice}</Text>}
    {['error', 'failed', 'cancelled'].includes(feedback.status) && <Text role="alert" fontSize="12px" color="orange.200" mt={2}>{feedback.run?.error === 'executor_feedback_iteration_limit' ? 'Связанный расчёт не сошёлся за заданное число итераций; ответ сети не показан.' : feedback.run?.error === 'executor_feedback_cycle' ? 'Расчёт обнаружил повторяющееся расписание обратной связи; ответ сети не показан.' : feedback.run?.error === 'executor_synapse_endpoint' ? 'Синапс находится на конце секции; корректная передача в этой точке пока не подтверждена. Расчёт остановлен.' : 'Связанный расчёт не завершён; ответ сети на сцене не показан.'}</Text>}
    {feedback.status === 'completed' && state.selected?.id === pendingFeedback && ['error', 'failed', 'cancelled', 'unavailable'].includes(proxy.status) && <Text role="alert" fontSize="12px" color="orange.200" mt={2}>Расчёт всей сети не завершён. Доступна запись выбранных клеток.</Text>}
    {feedback.status === 'failed' && Array.isArray(feedback.run?.result?.feedback_failure?.history) && <Text fontSize="12px" mt={1}>Завершено итераций: {feedback.run.result.feedback_failure.history.length}.</Text>}
    {state.error && <Text role="alert" fontSize="12px" color="orange.200" mt={2}>Не удалось загрузить расчёты.</Text>}
    {newest?.state === 'failed' && <Text role="alert" fontSize="12px" color="orange.200">{executorStartError(newest.error) || (newest.error === 'executor_contact_clearance' ? 'Контакт слишком близок к восстановленному отростку.' : newest.error === 'executor_contact_screen_unavailable' ? 'Индексы проверки контактов недоступны.' : geometryFailures ? 'Предварительная проверка выявила несколько расхождений.' : geometryFailure ? `Нейрон ${geometryFailure[1]}: не удалось сопоставить ${geometryFailure[2]} из ${geometryFailure[3]} синапсов в заданном допуске.` : newest.error === 'executor_synapse_geometry' ? 'Не все синапсы удалось сопоставить с отростками в заданном допуске.' : 'Расчёт не завершён. Проверьте параметры и состояние сервиса.')}</Text>}
  </Box>;
}
