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
import useFullPopulationFeedback from './useFullPopulationFeedback';
import AppSelect from '@shared/controls/AppSelect';
import { validFeedbackDuration } from '../feedbackDuration';
import { clearPendingFeedback, readFeedbackRetryDraft, readPendingFeedback, readSelectedFeedbackSource,
  writeFeedbackRetryDraft, writePendingFeedback, writeSelectedFeedbackSource } from './pendingFeedbackStorage';

const active = new Set(['queued', 'preparing', 'running', 'publishing', 'cancelling']);
const contacts = [['source_um', 'STIM+'], ['return_um', 'STIM−'], ['electrode_um', 'E1'], ['reference_um', 'REF']];
const tabStorage = () => { try { return window.sessionStorage; } catch { return null; } };

function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.keys(value).sort()
    .map(key => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(',')}}`;
  return JSON.stringify(value);
}

function recoveredDraft(receipt, source, sceneId, sceneManifest) {
  if (!receipt || receipt.sourceId !== source?.id || !['completed', 'failed', 'cancelled'].includes(source.state)
      || source.parent_run_id !== sceneId || source.configuration?.graph_manifest_sha256 !== sceneManifest) return null;
  try {
    const [scene, graph, positions, current, duration, ids, radius] = JSON.parse(receipt.signature);
    const simulation = source.configuration.simulation;
    if (scene !== sceneId || graph !== sceneManifest || !simulation || typeof ids !== 'string'
        || typeof radius !== 'string' || !radius.trim() || !Number.isFinite(Number(radius)) || Number(radius) < 0
        || !Array.isArray(source.configuration.source_ids)
        || canonicalJson(source.configuration.source_ids) !== canonicalJson(ids.split(',').map(value => Number(value.trim())))
        || Number(current) !== simulation.current_na || Number(duration) !== simulation.duration_ms
        || !contacts.every(([key]) => Array.isArray(positions?.[key]) && positions[key].length === 3
          && positions[key].every(Number.isFinite)
          && canonicalJson(positions[key]) === canonicalJson(simulation[key]))) return null;
    return { configuration: source.configuration, simulation, positions, ids, radius };
  } catch { return null; }
}

function unresolvedGeometryCount(code) {
  if (typeof code !== 'string') return null;
  const match = /^executor_synapse_geometries:([1-9]\d{0,18}:[1-9]\d{0,8}:[1-9]\d{0,8}(?:,[1-9]\d{0,18}:[1-9]\d{0,8}:[1-9]\d{0,8}){1,255});omitted:(\d{1,3})$/.exec(code);
  if (!match) return null;
  const rows = match[1].split(',').map(row => row.split(':'));
  const omitted = Number(match[2]);
  if (rows.length + omitted > 256 || new Set(rows.map(row => row[0])).size !== rows.length
      || rows.some(([id, count, total]) => BigInt(id) >= 2n ** 63n || Number(count) > Number(total))) return null;
  return rows.length + omitted;
}

function unresolvedGeometrySingle(code) {
  if (typeof code !== 'string') return null;
  const match = /^executor_synapse_geometry:([1-9]\d{0,18}):([1-9]\d{0,8}):([1-9]\d{0,8})$/.exec(code);
  return match && BigInt(match[1]) < 2n ** 63n && Number(match[2]) <= Number(match[3])
    ? match : null;
}

export default function FragmentPopulationRecording({ sceneRunId, sceneManifest, onShowOnBody, canRestore, incomingContacts, onConsumeContacts, onAdjustContact, onAdjustParameters, onSourceForFiles, formRef, onPrimaryStatus, onClearanceNotice, onFailure }) {
  const preset = fieldDemoPreset(sceneManifest);
  const [ids, setIds] = useState('174827, 176609');
  const [excludedIds, setExcludedIds] = useState([]);
  const [searchRadius, setSearchRadius] = useState('10');
  const [calculationMode, setCalculationMode] = useState('detailed');
  const operatorContactSignature = useRef(null);
  const launchedDirect = useRef(null);
  const launchedFull = useRef(null);
  const full = useFullPopulationFeedback(result => {
    if (launchedFull.current?.sceneId !== sceneRunId
        || launchedFull.current?.signature !== operatorContactSignature.current
        || result.configuration?.graph_manifest_sha256 !== sceneManifest) return;
    onShowOnBody?.(result, {});
  }, sceneRunId, {
    canResume: receipt => (!canRestore || canRestore()) && receipt.graph === sceneManifest,
    validateResume: (receipt, restored) => {
      const simulation = restored.configuration?.simulation;
      return (!canRestore || canRestore()) && restored.configuration?.graph_manifest_sha256 === sceneManifest
        && contacts.every(([key]) => Array.isArray(simulation?.[key])
          && simulation[key].length === 3 && simulation[key].every(Number.isFinite))
        && Number.isFinite(simulation.current_na)
        && JSON.stringify([contacts.map(([key]) => simulation[key]), simulation.current_na]) === receipt.signature;
    },
    onResume: (receipt, restored) => {
      const simulation = restored.configuration.simulation;
      launchedFull.current = { sceneId: sceneRunId, signature: receipt.signature };
      operatorContactSignature.current = receipt.signature;
      setCoordinates(Object.fromEntries(contacts.map(([key]) => [key, [...simulation[key]]])));
      setBaseConfiguration(restored.configuration);
      setCalculationMode('full');
      onAdjustContact?.({ kind: 'fragments', configuration: restored.configuration, simulation }, null);
    },
  });
  const direct = useDirectNetworkProxy((run, simulation) => {
    if (!simulation) return;
    const launched = launchedDirect.current;
    if (launched && (launched.sceneId !== sceneRunId
        || launched.signature !== operatorContactSignature.current)) return;
    if (!launched && canRestore && !canRestore()) return;
    onShowOnBody?.(run, { direct: true, simulation });
  }, sceneRunId, canRestore);
  const [, setSelectionBasis] = useState(null);
  const [coordinates, setCoordinates] = useState({
    source_um: [429.056, 387.68, 228.352], return_um: [929.056, 327.68, 228.352],
    electrode_um: [419.328, 379.488, 359.92], reference_um: [919.328, 319.488, 359.92],
  });
  const [state, setState] = useState({ items: [], selected: null, loading: true, error: false });
  useEffect(() => {
    const source = state.selected;
    onSourceForFiles?.(source?.state === 'completed' && source.parent_run_id === sceneRunId
      && source.configuration?.graph_manifest_sha256 === sceneManifest ? { sceneRunId, source } : null);
  }, [state.selected, sceneRunId, sceneManifest, onSourceForFiles]);
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
  const currentScene = useRef(null); currentScene.current = [sceneRunId, sceneManifest];
  const supersededSourceId = useRef(null);
  const launchedContactSignature = useRef(null);
  const launchedRetryDraft = useRef(null);
  const restoredRetryDraft = useRef(null);
  const draftEdited = useRef(false);
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
    if (['error', 'failed', 'interrupted'].includes(full.status)) onFailureRef.current?.();
  }, [full.status]);
  useEffect(() => {
    if (!['error', 'failed'].includes(feedback.status) || !pendingFeedback
        || feedback.sourceId !== pendingFeedback || reportedFeedbackFailure.current === pendingFeedback) return;
    reportedFeedbackFailure.current = pendingFeedback;
    onFailureRef.current?.();
  }, [feedback.status, feedback.sourceId, pendingFeedback]);
  useEffect(() => {
    if (feedback.status !== 'completed' || !feedback.run || !state.selected
        || (state.selected.id === pendingFeedback && ['idle', 'loading', ...active].includes(proxy.status))) return;
    if (state.selected.id === supersededSourceId.current) return;
    if (state.selected.id === launchedContactSignature.current?.sourceId
        && operatorContactSignature.current !== launchedContactSignature.current.signature) return;
    const shownKey = `${feedback.run.id}:${proxy.status === 'completed' ? proxy.run?.id : 'coupled'}`;
    if (shownFeedback.current === shownKey) return;
    const restore = state.selected.id !== pendingFeedback && state.selected.id !== autoShowRunId.current;
    if (restore && (draftEdited.current || (canRestore && !canRestore()))) return;
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
    const source = state.selected;
    if (feedback.status !== 'failed' || feedback.sourceId !== source?.id || pendingFeedback
        || draftEdited.current || incomingContacts || (canRestore && !canRestore())
        || restoredRetryDraft.current === source.id) return;
    const draft = recoveredDraft(launchedRetryDraft.current, source, sceneRunId, sceneManifest);
    if (!draft) return;
    restoredRetryDraft.current = source.id;
    setBaseConfiguration(draft.configuration);
    setCoordinates(draft.positions);
    setIds(draft.ids); setSearchRadius(draft.radius); setExcludedIds([]);
    setSelectionBasis(contactBasis(sceneRunId, sceneManifest, draft.simulation));
    onAdjustContact?.({ kind: 'fragments', configuration: draft.configuration,
      simulation: draft.simulation }, null);
  }, [feedback.status, feedback.sourceId, state.selected, pendingFeedback, sceneRunId, sceneManifest,
    canRestore, incomingContacts, onAdjustContact]);
  useEffect(() => {
    const source = state.items.find(item => item.id === launchedRetryDraft.current?.sourceId);
    if (!source || !['failed', 'cancelled'].includes(source.state) || pendingFeedback
        || draftEdited.current || incomingContacts || (canRestore && !canRestore())
        || restoredRetryDraft.current === source.id) return;
    const draft = recoveredDraft(launchedRetryDraft.current, source, sceneRunId, sceneManifest);
    if (!draft) return;
    restoredRetryDraft.current = source.id;
    setBaseConfiguration(draft.configuration); setCoordinates(draft.positions);
    setIds(draft.ids); setSearchRadius(draft.radius); setExcludedIds([]);
    setSelectionBasis(contactBasis(sceneRunId, sceneManifest, draft.simulation));
    onAdjustContact?.({ kind: 'fragments', configuration: draft.configuration,
      simulation: draft.simulation }, null);
  }, [state.items, pendingFeedback, sceneRunId, sceneManifest, canRestore, incomingContacts, onAdjustContact]);
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
    launchedDirect.current = null;
    launchedRetryDraft.current = readFeedbackRetryDraft(tabStorage(), sceneRunId);
    restoredRetryDraft.current = null;
    draftEdited.current = false;
    restoredScene.current = null;
    supersededSourceId.current = null;
    launchedContactSignature.current = null;
    selectedRunId.current = receipt?.sourceId || readSelectedFeedbackSource(tabStorage(), sceneRunId)
      || launchedRetryDraft.current?.sourceId;
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
    if (!canRestore || !canRestore()) draftEdited.current = true;
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
  }, [incomingContacts, onConsumeContacts, sceneManifest, sceneRunId, canRestore]);
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
                && ((progress.phase === 'network' && (progress.done === 0 && progress.total === 0
                  || progress.total > 0 && progress.total <= 1000 && progress.done >= 0 && progress.done <= progress.total))
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
  operatorContactSignature.current = JSON.stringify([contacts.map(([key]) => coordinates[key].map(Number)), Number(stimulusCurrent)]);
  const simulationSettings = baseConfiguration?.simulation || preset?.simulation;
  const duration = simulationSettings?.duration_ms ?? '';
  const validCurrent = String(stimulusCurrent).trim() !== '' && Number.isFinite(Number(stimulusCurrent));
  const validDuration = validFeedbackDuration(simulationSettings, duration);
  const validSearchRadius = searchRadius.trim() !== '' && Number.isFinite(Number(searchRadius)) && Number(searchRadius) >= 0;
  const draftSignature = JSON.stringify([sceneRunId, sceneManifest, coordinates, stimulusCurrent, duration, ids, searchRadius]);
  const latestDraft = useRef(draftSignature); latestDraft.current = draftSignature;
  const running = state.items.some(item => active.has(item.state));
  const primaryReady = Boolean(preset && sceneRunId && (calculationMode !== 'detailed' || validIds) && validCoordinates && validCurrent && validDuration && (calculationMode !== 'detailed' || validSearchRadius) && !sending && !running && !state.loading && !state.error);
  const feedbackRunning = ['loading', 'queued', 'preparing', 'running', 'publishing', 'cancelling'].includes(feedback.status);
  const proxyRunning = feedback.status === 'completed' && state.selected?.id === pendingFeedback
    && ['idle', 'loading', 'queued', 'preparing', 'running', 'publishing', 'cancelling'].includes(proxy.status);
  useEffect(() => {
    const inProgress = running || sending || feedbackRunning || proxyRunning || direct.running || full.running;
    const sourceState = state.items.find(item => item.id === pendingFeedback)?.state;
    const stage = sending ? (preparationStage || 'Проверка контактов') : running
      ? ({ queued: 'Ожидание запуска', preparing: 'Подготовка модели', running: 'Расчёт нейронов', publishing: 'Сохранение записи', cancelling: 'Остановка' }[sourceState] || 'Расчёт нейронов')
      : feedbackRunning ? ({ queued: 'Ожидание расчёта сети', preparing: 'Подготовка сети', running: 'Расчёт сети', publishing: 'Сохранение ответа', cancelling: 'Остановка' }[feedback.status] || 'Подготовка сети')
      : full.running ? 'Связанный расчёт ЦНС' : proxyRunning || direct.running ? 'Модель всей сети ЦНС' : null;
    onPrimaryStatus?.({ ready: primaryReady && !feedbackRunning && !proxyRunning && !direct.running && !full.running, running: inProgress,
      ...(stage ? { stage, phase: full.running
        ? (full.progress?.phase === 'full_feedback' ? 2 : ['full_control', 'full_control_feedback'].includes(full.progress?.phase) ? 1 : 0)
        : sending ? 0 : running ? 1 : 2,
        canCancel: !cancelling && (Boolean(full.run?.id && full.running) || Boolean(direct.run?.id && direct.running) || (sending && !submitting) || Boolean(state.items.find(item => item.id === pendingFeedback && active.has(item.state))) || Boolean(feedback.run && active.has(feedback.status)) || Boolean(proxy.run && active.has(proxy.status))),
        progress: running && sourceProgress?.runId === pendingFeedback ? sourceProgress
          : feedbackRunning ? feedback.progress : full.running ? full.progress : proxyRunning ? proxy.progress : direct.running ? direct.progress : null,
        connectionLost: Boolean((feedbackRunning && feedback.connectionLost) || (proxyRunning && proxy.connectionLost)
          || (direct.running && direct.connectionLost) || (full.running && full.connectionLost)),
        cancel: cancelAction } : {}) });
  }, [onPrimaryStatus, primaryReady, running, sending, preparationStage, submitting, feedbackRunning, feedback.status, feedback.run, feedback.progress, feedback.connectionLost, proxyRunning, proxy.status, proxy.run, proxy.progress, proxy.connectionLost, direct.running, direct.progress, direct.connectionLost, direct.run?.id, full.running, full.run?.id, full.progress, full.connectionLost, state.items, pendingFeedback, cancelling, cancelAction, sourceProgress]);
  const submit = async event => {
    event.preventDefault();
    if (!preset || (calculationMode === 'detailed' && !validIds) || !validCoordinates || !validCurrent || !validDuration || (calculationMode === 'detailed' && !validSearchRadius) || sending || running || feedbackRunning || proxyRunning || direct.running || full.running || state.loading || state.error) return;
    const original = baseConfiguration || { graph_manifest_sha256: sceneManifest, source_ids: [], seed: 1,
      simulation: preset.simulation, threshold_mv: -20, max_distance_um: 2 };
    const simulation = { ...original.simulation, ...Object.fromEntries(contacts.map(([key]) => [key, coordinates[key].map(Number)])), allow_disconnected: true };
    if (calculationMode === 'full') {
      const preparation = new AbortController(); preparationRequest.current = preparation;
      setPreparationStage('Проверка контактов'); setSending(true); setSubmitError('');
      try {
        const screen = await simulationApi.contactPositions(sceneRunId, {
          positions_um: contacts.map(([key]) => simulation[key]), clearance_um: simulation.clearance_um,
        }, preparation.signal);
        if (preparation.signal.aborted) return;
        if (latestDraft.current !== draftSignature) throw new Error('changed_contacts');
        if (!Array.isArray(screen?.potential_intersections)
            || screen.potential_intersections.some(row => !Array.isArray(row?.contact_indices)
              || !row.contact_indices.length || row.contact_indices.some(index => !Number.isInteger(index)
                || index < 0 || index >= contacts.length))) throw new Error('invalid_contact_screen');
        if (screen.potential_intersections.length) {
          setSubmitError('Контакты слишком близко к отросткам. Переместите их и повторите запуск.');
          onFailure?.(); return;
        }
        const synapse = { weight_us: .001, tau1_ms: .2, tau2_ms: 2, reversal_mv: 0 };
        launchedFull.current = { sceneId: sceneRunId, signature: operatorContactSignature.current };
        await full.start({ graph_manifest_sha256: sceneManifest,
          simulation: { ...simulation, pulse_count: simulation.pulse_count ?? null,
            pulse_interval_ms: simulation.pulse_interval_ms ?? null },
          excitatory: synapse, inhibitory: { ...synapse, reversal_mv: -80 }, threshold_mv: -20,
          max_source_distance_um: 2, max_target_distance_um: 2, max_iterations: 16,
          max_events: 1000000, allow_known_geometry_repair: true },
        { signature: operatorContactSignature.current });
      } catch {
        if (!preparation.signal.aborted) {
          setSubmitError('Не удалось проверить контакты. Повторите запуск.'); onFailure?.();
        }
      } finally {
        if (preparationRequest.current === preparation) preparationRequest.current = null;
        setSending(false); setPreparationStage(null);
      }
      return;
    }
    if (calculationMode === 'fast') {
      const preparation = new AbortController(); preparationRequest.current = preparation;
      setPreparationStage('Проверка контактов'); setSending(true); setSubmitError('');
      try {
        // E1 and REF do not contribute to the fast network-only calculation.
        const screen = await simulationApi.contactPositions(sceneRunId, {
          positions_um: [simulation.source_um, simulation.return_um], clearance_um: simulation.clearance_um,
        }, preparation.signal);
        if (preparation.signal.aborted) return;
        if (latestDraft.current !== draftSignature) {
          setSubmitError('Положение или параметры изменились во время проверки. Запустите расчёт снова.'); onFailure?.(); return;
        }
        if (!Array.isArray(screen?.potential_intersections)
            || screen.potential_intersections.some(row => !Array.isArray(row?.contact_indices)
              || !row.contact_indices.length || new Set(row.contact_indices).size !== row.contact_indices.length
              || row.contact_indices.some(index => !Number.isInteger(index) || index < 0 || index > 1)))
          throw new Error('invalid_contact_screen');
        const affected = [...new Set(screen.potential_intersections.flatMap(row => row.contact_indices))].sort();
        if (affected.length) {
          setSubmitError(`Возможное пересечение контактов ${affected.map(index => contacts[index][1]).join(', ')} с отростками. Переместите их и повторите запуск.`);
          onFailure?.(); return;
        }
        preparationRequest.current = null; setSending(false); setPreparationStage(null);
        launchedDirect.current = { sceneId: sceneRunId, signature: operatorContactSignature.current };
        await direct.start(sceneRunId, { request_id: crypto.randomUUID(), simulation,
          graph_manifest_sha256: sceneManifest, seed: original.seed, gain: 1000000,
          allow_partial_geometry: true, allow_missing_curvature: true, allow_contact_exclusion: false });
      } catch (error) {
        if (preparation.signal.aborted) return;
        const status = error?.status ?? error?.response?.status;
        setSubmitError(status === 429 ? 'Проверка контактов занята другим запросом. Повторите запуск позже.'
          : 'Не удалось проверить контакты. Повторите запуск.');
        onFailure?.();
      } finally {
        if (preparationRequest.current === preparation) preparationRequest.current = null;
        setSending(false); setPreparationStage(null);
      }
      return;
    }
    const reusableSource = state.selected?.id && feedback.sourceId === state.selected.id
        && state.selected.state === 'completed' && state.selected.parent_run_id === sceneRunId
        && state.selected.configuration?.graph_manifest_sha256 === sceneManifest
        && launchedRetryDraft.current?.sourceId === state.selected.id
        && launchedRetryDraft.current.signature === draftSignature
        && canonicalJson(state.selected.configuration.simulation) === canonicalJson(simulation)
        && canonicalJson(state.selected.configuration.source_ids) === canonicalJson(idsList.map(Number))
        && state.selected.configuration.seed === original.seed
        && state.selected.configuration.threshold_mv === original.threshold_mv
        && state.selected.configuration.max_distance_um === original.max_distance_um
        && supersededSourceId.current !== state.selected.id;
    if (reusableSource && ['failed', 'error'].includes(feedback.status)) {
      setSubmitError('');
      feedback.retry();
      return;
    }
    if (reusableSource && feedback.status === 'completed'
        && ['failed', 'error', 'cancelled', 'unavailable'].includes(proxy.status)
        && typeof proxy.retry === 'function') {
      setSubmitError(''); reportedProxyFailure.current = null;
      if (pendingFeedback !== state.selected.id) {
        const resumeId = crypto.randomUUID();
        writePendingFeedback(tabStorage(), sceneRunId, { version: 1, sourceId: state.selected.id, requestId: resumeId });
        setFeedbackRequestId(resumeId); setFeedbackRetryReceipt(false); setPendingFeedback(state.selected.id);
      }
      proxy.retry();
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
        if (new Set(sourceIds).size !== sourceIds.length) {
          setSubmitError('Поиск вернул повторяющиеся нейроны. Расчёт остановлен; повторите запрос.');
          onFailure?.(); return;
        }
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
      if (currentScene.current[0] !== sceneRunId || currentScene.current[1] !== sceneManifest) {
        requestId.current = null;
        return;
      }
      launchedContactSignature.current = { sourceId: created.id,
        signature: JSON.stringify([contacts.map(([key]) => simulation[key]), Number(simulation.current_na)]) };
      if (latestDraft.current !== draftSignature) {
        supersededSourceId.current = created.id;
        setState(previous => ({ ...previous, items: [created, ...previous.items.filter(item => item.id !== created.id)] }));
        selectedRunId.current = created.id;
        setFeedbackRequestId(resumeRequest); setFeedbackRetryReceipt(false); setPendingFeedback(created.id);
        requestId.current = null; setRetry(value => value + 1);
        setSubmitError('Расчёт запущен с прежними параметрами; изменённое положение сохранено как черновик.');
        onFailure?.(); return;
      }
      supersededSourceId.current = null;
      launchedRetryDraft.current = { sourceId: created.id,
        signature: JSON.stringify([sceneRunId, sceneManifest,
          Object.fromEntries(contacts.map(([key]) => [key, [...simulation[key]]])),
          stimulusCurrent, duration, sourceIds.join(', '),
          selectionRadius === null ? searchRadius : String(selectionRadius)]) };
      writeFeedbackRetryDraft(tabStorage(), sceneRunId, launchedRetryDraft.current);
      writeSelectedFeedbackSource(tabStorage(), sceneRunId, created.id);
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
  const newest = state.items.find(item => item.id === pendingFeedback)
    || state.items.find(item => item.id === selectedRunId.current) || state.items[0];
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
  const geometryFailure = unresolvedGeometrySingle(newest?.error);
  const geometryFailureCount = unresolvedGeometryCount(newest?.error);
  const cancel = async () => {
    if (full.running) { await full.cancel(); return; }
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
          isDisabled={running || sending || feedbackRunning || proxyRunning || direct.running || full.running}
          options={[{ value: 'detailed', label: 'Подробный' }, { value: 'fast', label: 'Быстрый' }, { value: 'full', label: 'Полная ЦНС · экспериментальный' }]} />
        {calculationMode === 'fast' && <Text fontSize="11px" color={SIMULATION_THEME.textSecondary}>Упрощённая сеть; запись E1–REF не рассчитывается.</Text>}
        {calculationMode === 'full' && <Text fontSize="11px" color={SIMULATION_THEME.textSecondary}>Экспериментальная модель: параметры синапсов не откалиброваны. При неполной геометрии расчёт остановится.</Text>}
      </FormControl>
      <FormControl maxW="200px" isInvalid={!validCurrent}>
        <FormLabel fontSize="12px">Ток STIM, нА</FormLabel>
        <Input size="sm" type="number" isDisabled={!preset || running || sending || feedbackRunning || full.running} value={stimulusCurrent} onChange={event => {
          const value = event.target.value;
          const current = value === '' ? '' : Number(value);
          if (current === stimulusCurrent) return;
          draftEdited.current = true;
          const original = baseConfiguration || { graph_manifest_sha256: sceneManifest, source_ids: [], seed: 1,
            simulation: preset.simulation, threshold_mv: -20, max_distance_um: 2 };
          const simulation = { ...original.simulation,
            ...Object.fromEntries(contacts.map(([key]) => [key, [...coordinates[key]]])), current_na: current };
          const configuration = { ...original, simulation };
          setBaseConfiguration(configuration);
          onAdjustParameters?.({ kind: 'fragments', configuration, simulation });
          requestId.current = null;
        }} />
        {validCurrent && Number(stimulusCurrent) === 0 && <Text fontSize="11px" color={SIMULATION_THEME.textSecondary} mt={1}>Контроль без электрического воздействия; остальные параметры сохраняются.</Text>}
      </FormControl>
      {calculationMode === 'detailed' && <FormControl maxW="200px" mt={3} isInvalid={!validSearchRadius}>
        <FormLabel fontSize="12px">Радиус поиска, мкм</FormLabel>
        <Input size="sm" type="number" min={0} isDisabled={running || sending || feedbackRunning} value={searchRadius} onChange={event => { draftEdited.current = true; setSearchRadius(event.target.value); setSelectionBasis('radius-changed'); requestId.current = null; }} />
      </FormControl>}
    </Box>
    {submitError && <Text role="alert" fontSize="12px" color="orange.200" mt={2}>{submitError}</Text>}
    {['error', 'failed', 'cancelled', 'interrupted'].includes(full.status) && <Text role="alert" fontSize="12px" color="orange.200" mt={2}>{full.run?.error === 'executor_synapse_geometry' ? 'Не все синапсы удалось сопоставить с морфологией. Полный расчёт остановлен.' : 'Полный связанный расчёт не завершён. Проверьте состояние сервиса.'}</Text>}
    {['error', 'failed'].includes(direct.status) && <Text role="alert" fontSize="12px" color="orange.200" mt={2}>{executorStartError(direct.run?.error) || 'Быстрый расчёт не завершён. Проверьте параметры и состояние сервиса.'}</Text>}
    {clearanceNotice && <Text role="status" fontSize="12px" color={SIMULATION_THEME.textSecondary} mt={2}>{clearanceNotice}</Text>}
    {['error', 'failed', 'cancelled'].includes(feedback.status) && <Text role="alert" fontSize="12px" color="orange.200" mt={2}>{feedback.run?.error === 'executor_feedback_iteration_limit' ? 'Связанный расчёт не сошёлся за заданное число итераций; ответ сети не показан.' : feedback.run?.error === 'executor_feedback_cycle' ? 'Расчёт обнаружил повторяющееся расписание обратной связи; ответ сети не показан.' : feedback.run?.error === 'executor_synapse_endpoint' ? 'Синапс находится на конце секции; корректная передача в этой точке пока не подтверждена. Расчёт остановлен.' : 'Связанный расчёт не завершён; ответ сети на сцене не показан.'}</Text>}
    {feedback.status === 'completed' && state.selected?.id === pendingFeedback && ['error', 'failed', 'cancelled', 'unavailable'].includes(proxy.status) && <Text role="alert" fontSize="12px" color="orange.200" mt={2}>Расчёт всей сети не завершён. Доступна запись выбранных клеток.</Text>}
    {feedback.status === 'failed' && Array.isArray(feedback.run?.result?.feedback_failure?.history) && <Text fontSize="12px" mt={1}>Завершено итераций: {feedback.run.result.feedback_failure.history.length}.</Text>}
    {state.error && <Text role="alert" fontSize="12px" color="orange.200" mt={2}>Не удалось загрузить расчёты.</Text>}
    {newest?.state === 'failed' && <Text role="alert" fontSize="12px" color="orange.200">{executorStartError(newest.error) || (newest.error === 'executor_contact_clearance' ? 'Контакт слишком близок к восстановленному отростку.' : newest.error === 'executor_contact_screen_unavailable' ? 'Индексы проверки контактов недоступны.' : geometryFailureCount ? `Не удалось сопоставить синапсы для ${geometryFailureCount} нейронов; расчёт остановлен.` : geometryFailure ? `Нейрон ${geometryFailure[1]}: не удалось сопоставить ${geometryFailure[2]} из ${geometryFailure[3]} синапсов в заданном допуске.` : newest.error === 'executor_synapse_geometry' ? 'Не все синапсы удалось сопоставить с отростками в заданном допуске.' : 'Расчёт не завершён. Проверьте параметры и состояние сервиса.')}</Text>}
  </Box>;
}
