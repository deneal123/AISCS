import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert, AlertIcon, Box, Button, ButtonGroup, CloseButton, Flex, FormControl, FormLabel,
  HStack, IconButton, Input, Stack, Text, Tooltip, useBreakpointValue, usePrefersReducedMotion,
} from '@chakra-ui/react';
import { FiActivity, FiCrosshair, FiMaximize, FiMenu, FiMinimize, FiPause, FiPlay, FiRepeat, FiSettings, FiSquare, FiZoomIn } from 'react-icons/fi';
import { useSearchParams } from 'react-router-dom';
import { SIMULATION_THEME as CHAT_THEME, SIMULATION_FONT_FAMILY as CHAT_FONT_FAMILY, SIMULATION_TRACES } from './theme';
import { simulationApi } from './api';
import SignalPlot from './recording/SignalPlot';
import ReplayRecording from './recording/ReplayRecording';
import FieldRecordingModes from './recording/FieldRecordingModes';
import SimulationProgress from './components/SimulationProgress';
import SimulationSidebar from './components/SimulationSidebar';
import SceneVisibilityControls from './components/SceneVisibilityControls';
import { fieldDemoPreset } from './field/fieldDemoPreset';
import RecognitionSummary from './RecognitionSummary';
import SimulatorScene from './SimulatorScene';
import SimulationComparison from './SimulationComparison';
import { createCameraLink } from './scene/sceneCamera';
import useSimulationHistory from './useSimulationHistory';
import SimulationFiles from './recording/SimulationFiles';
import useSimulationFullscreen from './useSimulationFullscreen';
import { placementIssue, comparisonIssue, comparisonSceneIssue, comparisonReference, updateContactPosition } from './scene/sceneModel';
import { prefersReducedMotion } from '../../utils/motion';
import AppSelect from '@shared/controls/AppSelect';
import { sensoryInputName } from './scene/stimulusRegions';
import { executorStartError } from './executorStartError';
import { preventSimulatorPageZoom } from './pageZoomGuard';
import { targetTimeline } from './recording/targetTimeline';
import { contactNormalsForSimulation, directFieldMatchesScene, fieldExclusionNotice, fieldProxyActivityNotice, fieldProxyExplanation, fieldResultDescription, fieldResultHeading } from './recording/recordingScope';
import { scenePlayback } from './recording/scenePlayback';
import { verifiedHistogramForScene } from './recording/electricalTimeline';
import DiscretizationNotice from './recording/DiscretizationNotice';

const labels = { none: 'Нет воздействия', weak: 'Слабое воздействие', strong: 'Сильное воздействие' };
const busyStates = new Set(['queued', 'preparing', 'running', 'publishing', 'cancelling']);
const NETWORK_WARNING = 'Связь прервана. Опыт сохранён; восстановление соединения…';
const COMPARISON_UNAVAILABLE = 'Закреплённая запись A недоступна. Опыт B открыт без сравнения.';
const clone = value => JSON.parse(JSON.stringify(value));
const uuid = () => crypto.randomUUID();
const CNS_MODEL_ID = 'male-cns-hybrid-v1';
const defaultModel = catalog => {
  const model = catalog.models.find(item => item.id === CNS_MODEL_ID);
  if (!model) throw new Error('CNS model unavailable');
  return model;
};

function Range({ label, value, onChange, min = 0, max = 1, step = 0.05 }) {
  return <FormControl>
    <HStack justify="space-between" mb={2}><FormLabel m={0} fontSize="13px">{label}</FormLabel><Text fontSize="12px" color={CHAT_THEME.textSecondary}>{Number(value).toFixed(2)}</Text></HStack>
    <input type="range" aria-label={label} min={min} max={max} step={step} value={value}
      onChange={event => onChange(Number(event.target.value))} style={{ width: '100%', accentColor: '#2D5BFF', cursor: 'pointer' }} />
  </FormControl>;
}

export default function SimulatorPage() {
  useEffect(() => {
    window.addEventListener('wheel', preventSimulatorPageZoom, { passive: false, capture: true });
    return () => window.removeEventListener('wheel', preventSimulatorPageZoom, { capture: true });
  }, []);
  const [searchParams, setSearchParams] = useSearchParams();
  const initialRunId = useRef(searchParams.get('run'));
  const initialComparisonId = useRef(searchParams.get('compare'));
  const initialComparisonView = useRef(searchParams.get('view') === 'comparison');
  const [catalog, setCatalog] = useState(null), [config, setConfig] = useState(null);
  const [run, setRun] = useState(null);
  const [fieldPlayback, setFieldPlayback] = useState(null);
  const [fieldSourceForFiles, setFieldSourceForFiles] = useState(null);
  const [fieldContactDraft, setFieldContactDraft] = useState(null);
  const [fieldDisplayNormals, setFieldDisplayNormals] = useState(null);
  const [fieldContactPick, setFieldContactPick] = useState(null);
  const [fieldClearanceNotice, setFieldClearanceNotice] = useState('');
  const [fieldSnapRequest, setFieldSnapRequest] = useState(0);
  const primaryStimForm = useRef(null);
  const [primaryStimStatus, setPrimaryStimStatus] = useState({ ready: false, running: false });
  const updatePrimaryStimStatus = useCallback(status => setPrimaryStimStatus(status), []);
  const preparedFieldScene = useRef(null);
  const fieldUserEdited = useRef(false);
  const freshExperiment = useRef(false);
  const consumeFieldContacts = useCallback(() => setFieldContactDraft(previous => previous && ({ ...previous, delivered: true })), []);
  const [motorState, setMotorState] = useState(null);
  const receiveMotorReadout = useCallback(value => setMotorState(value), []);
  const [fieldEventsState, setFieldEventsState] = useState(null);
  const receiveFieldEvents = useCallback(value => setFieldEventsState(value), []);
  const history = useSimulationHistory(), { runs, replace: replaceHistory, refresh: refreshRuns } = history;
  const [tab, setTab] = useState('scene'), [sidebarChoice, setSidebarChoice] = useState(null);
  const isCompact = useBreakpointValue({ base: true, md: false });
  const sidebar = sidebarChoice ?? !isCompact;
  const [drawer, setDrawer] = useState(false), [placing, setPlacing] = useState(false);
  const [stimPanel, setStimPanel] = useState(false);
  const [recordingDetails, setRecordingDetails] = useState(false);
  const [nociceptionOpen, setNociceptionOpen] = useState(false);
  const [nociceptionVisible, setNociceptionVisible] = useState(true);
  const [replayTime, setReplayTime] = useState(0);
  const [contact, setContact] = useState('electrode'), [opacity, setOpacity] = useState(1);
  const [neurons, setNeurons] = useState(true), [resetCamera, setResetCamera] = useState(0);
  const [bodyVisible, setBodyVisible] = useState(true), [regionsVisible, setRegionsVisible] = useState(true);
  const [focusLocal, setFocusLocal] = useState(0);
  const [nativeView, setNativeView] = useState(false);
  const [localWindow, setLocalWindow] = useState(true);
  const [pickingStimulus, setPickingStimulus] = useState(false);
  const cameraLink = useMemo(createCameraLink, []);
  const [pending, setPending] = useState(false), [error, setError] = useState('');
  const fullscreen = useSimulationFullscreen(setError);
  const [selecting, setSelecting] = useState(false), [connectAttempt, setConnectAttempt] = useState(0);
  const [retryingComparison, setRetryingComparison] = useState(false);
  const [notice, setNotice] = useState('Выберите грудную область для локальной модели регистрации.');
  const [timeMs, setTimeMs] = useState(0), [playing, setPlaying] = useState(false);
  const [targetPlayback, setTargetPlayback] = useState(null);
  useEffect(() => { setTargetPlayback(null); }, [fieldPlayback?.run?.id]);
  const [playbackRate, setPlaybackRate] = useState('0.02');
  const [loop, setLoop] = useState(true);
  const [showResponse, setShowResponse] = useState(true);
  const [comparison, setComparison] = useState(null), [profileReady, setProfileReady] = useState(false);
  const draftPlacement = useRef(null), fieldEditOriginal = useRef(null), pendingRequest = useRef(null), settingsButton = useRef(null);
  const selectionSequence = useRef(0), placementInvoker = useRef(null);
  const selectionRequest = useRef(null);
  const reducedMotion = usePrefersReducedMotion();
  const selectedId = useRef(null); selectedId.current = run?.id;
  const renderedVersion = useRef(''); renderedVersion.current = run?.updated_at || '';
  const busy = busyStates.has(run?.state), preview = run?.result?.preview;
  const activeField = tab === 'scene' && !fieldContactDraft && fieldPlayback && fieldPlayback.sceneRunId === run?.id ? fieldPlayback.run : null;
  const sceneField = activeField && fieldPlayback?.proxy ? fieldPlayback.proxy : activeField;
  const verifiedProxyHistogram = verifiedHistogramForScene(fieldEventsState, run?.id, sceneField, preview?.connectome);
  const activeFieldConfig = activeField ? (fieldPlayback.source?.configuration || activeField.configuration) : null;
  const activeFieldPreview = activeField?.result?.preview?.timeline || activeField?.result?.preview;
  const activeTarget = targetTimeline(activeField, targetPlayback);
  const motorReadout = motorState?.runId === run?.id && motorState?.fieldRunId === (sceneField?.id || null) ? motorState?.data : null;
  const playbackPreview = useMemo(() => scenePlayback({ activeField, activeFieldConfig, activeFieldPreview,
    activeTarget, fieldContactDraft, direct: fieldPlayback?.direct, motorReadout, preview, sceneField, verifiedProxyHistogram }),
  [activeField, activeFieldConfig, activeFieldPreview, activeTarget, fieldContactDraft, fieldPlayback?.direct,
    motorReadout, preview, sceneField, verifiedProxyHistogram]);
  const model = catalog?.models.find(item => item.id === config?.model_id) || catalog?.models[0];
  const displayedModel = preview ? catalog?.models.find(item => item.id === run?.configuration.model_id) || model : model;
  const fullCns = config?.model_id === 'male-cns-hybrid-v1';
  const displayedFullCns = displayedModel?.id === 'male-cns-hybrid-v1';
  const electricalPrimary = Boolean(displayedFullCns && preview?.connectome);
  useEffect(() => {
    const sceneId = run?.id, manifest = preview?.connectome?.manifest_sha256;
    fieldUserEdited.current = false;
    if (!sceneId) { preparedFieldScene.current = null; return; }
    if (!manifest || preparedFieldScene.current === sceneId) return;
    const preset = fieldDemoPreset(manifest);
    if (!preset) return;
    preparedFieldScene.current = sceneId;
    const configuration = { graph_manifest_sha256: manifest, source_ids: [174827, 176609], seed: 1,
      simulation: { ...preset.simulation, allow_disconnected: true }, threshold_mv: -20, max_distance_um: 2 };
    setFieldContactDraft({ sceneRunId: sceneId, kind: 'fragments', configuration,
      simulation: clone(configuration.simulation), changed: false, delivered: false });
    setFieldSnapRequest(value => value + 1);
  }, [run?.id, preview?.connectome?.manifest_sha256]);
  useEffect(() => { setNativeView(false); }, [run?.id, tab, config?.model_id]);
  const showView = (mode, id = run?.id, reference = comparison) => {
    setTab(mode);
    setSearchParams({ ...(id ? { run: id } : {}), ...(reference ? { compare: reference.run_id } : {}),
      ...(mode === 'comparison' && reference ? { view: 'comparison' } : {}) }, { replace: true });
  };

  useEffect(() => {
    const controller = new AbortController();
    (async () => {
      try {
        const profile = await simulationApi.profile(controller.signal);
        if (!profile.capabilities?.simulation) throw new Error('profile');
        setProfileReady(true);
        const result = await simulationApi.catalog(controller.signal);
        const list = await simulationApi.list(controller.signal);
        let selected, selectionWarning = '', legacySelection = false, templateSelection = false;
        if (initialRunId.current) {
          try {
            selected = await simulationApi.get(initialRunId.current, controller.signal);
            if (selected.configuration?.model_id !== CNS_MODEL_ID) {
              selected = null; legacySelection = true;
              selectionWarning = 'Старый опыт не поддерживается на странице симулятора. Открыта модель ЦНС.';
            }
          } catch (err) {
            if (controller.signal.aborted) return;
            if (![403, 404, 422].includes(err.status ?? err.response?.status)) throw err;
            selectionWarning = 'Запись недоступна. Выберите опыт из списка или создайте новый.';
          }
        }
        if (!selected && (!initialRunId.current || legacySelection)) {
          const latestCns = list.items?.find(item => item.state === 'completed'
            && item.configuration?.model_id === 'male-cns-hybrid-v1');
          if (latestCns) {
            try {
              selected = await simulationApi.get(latestCns.id, controller.signal);
              if (!selected?.result?.preview?.connectome?.manifest_sha256) selected = null;
            }
            catch (err) { if (controller.signal.aborted) throw err; selectionWarning = 'Последний опыт недоступен. Выберите другой из списка.'; }
          }
          if (!selected) {
            try { selected = await simulationApi.sceneTemplate(controller.signal); templateSelection = true; }
            catch (err) { if (controller.signal.aborted) throw err; if ((err.status ?? err.response?.status) !== 404) throw err; }
          }
        }
        let reference = null, comparisonWarning = '';
        if (initialComparisonId.current) {
          try {
            reference = comparisonReference(initialComparisonId.current === selected?.id ? selected
              : await simulationApi.get(initialComparisonId.current, controller.signal));
            if (!reference) comparisonWarning = 'Закреплённая запись A ещё не завершена. Опыт B открыт без сравнения.';
          } catch {
            comparisonWarning = COMPARISON_UNAVAILABLE;
          }
        }
        if (controller.signal.aborted) return;
        replaceHistory(list); setCatalog(result); setConfig(clone(selected?.configuration || defaultModel(result).defaults));
        if ((selected?.configuration || defaultModel(result).defaults).model_id === 'male-cns-hybrid-v1') { setOpacity(.18); setLocalWindow(false); setShowResponse(false); setNotice('Для отображения ЦНС запустите начальный расчёт или выберите сохранённый.'); }
        setComparison(reference); setTab(reference && initialComparisonView.current ? 'comparison' : 'scene');
        if (selectionWarning || comparisonWarning) setError(selectionWarning || comparisonWarning);
        if (selected) { freshExperiment.current = templateSelection; setRun(selected); setPlaying(!templateSelection && selected.state === 'completed' && !prefersReducedMotion()); }
      } catch (err) {
        if (!controller.signal.aborted) setError('Не удалось подключиться к симулятору. Проверьте доступность вычислительного контура и повторите загрузку.');
      }
    })();
    return () => controller.abort();
  }, [connectAttempt, replaceHistory]);

  useEffect(() => {
    return () => { selectionSequence.current += 1; selectionRequest.current?.abort(); };
  }, []);

  useEffect(() => {
    if (!run?.id || selecting || !busyStates.has(run.state)) return undefined;
    const id = run.id, controller = new AbortController();
    let timer, reconnectTimer, socket, polling = false, lastVersion = renderedVersion.current, terminal = false;
    const accept = async fresh => {
      if (selectedId.current !== id || controller.signal.aborted || (fresh.updated_at && fresh.updated_at < lastVersion)) return;
      lastVersion = fresh.updated_at || lastVersion;
      setError(value => value === NETWORK_WARNING ? '' : value);
      setRun(fresh);
      if (fresh.state === 'completed' && !terminal) { terminal = true; setTimeMs(0); setPlaying(!prefersReducedMotion()); await refreshRuns(); }
      else if (fresh.state === 'failed') setError(`Расчёт не завершён: ${executorStartError(fresh.error) || fresh.error || 'проверьте параметры и повторите опыт'}`);
    };
    const poll = async () => {
      if (polling || controller.signal.aborted) return;
      polling = true; clearTimeout(timer);
      try {
        const fresh = await simulationApi.get(id, controller.signal);
        await accept(fresh);
        if (busyStates.has(fresh.state)) timer = setTimeout(poll, socket?.readyState === 1 ? 4000 : 800);
      } catch {
        if (!controller.signal.aborted) { setError(NETWORK_WARNING); timer = setTimeout(poll, 2000); }
      } finally { polling = false; }
    };
    const connect = () => {
      if (controller.signal.aborted) return;
      try { socket = new WebSocket(simulationApi.eventsUrl(id)); } catch { return; }
      socket.onmessage = message => {
        if (controller.signal.aborted || selectedId.current !== id) return;
        try {
          const payload = JSON.parse(message.data);
          if (payload.type === 'snapshot' && payload.run?.id === id) accept(payload.run).catch(() => {});
          else if (payload.event?.run_id === id) poll();
        } catch { /* Periodic HTTP reconciliation remains authoritative. */ }
      };
      socket.onclose = () => {
        if (!controller.signal.aborted) { reconnectTimer = setTimeout(connect, 2000); poll(); }
      };
    };
    connect();
    timer = setTimeout(poll, 300);
    return () => { controller.abort(); clearTimeout(timer); clearTimeout(reconnectTimer); socket?.close(); };
  }, [run?.id, run?.state, refreshRuns, reducedMotion, selecting]);

  useEffect(() => {
    if (!playing || !playbackPreview) return undefined;
    let frame, previous;
    const tick = now => {
      const elapsed = previous ? Math.min(now - previous, 100) : 0; previous = now;
      setTimeMs(value => {
        const next = value + elapsed * Number(playbackRate);
        if (next >= playbackPreview.time_ms.at(-1)) { if (loop) return next % playbackPreview.time_ms.at(-1); setPlaying(false); return playbackPreview.time_ms.at(-1); }
        return next;
      });
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, playbackPreview, loop, playbackRate]);
  useEffect(() => { if (reducedMotion) setPlaying(false); }, [reducedMotion]);
  useEffect(() => { if (tab === 'files') setPlaying(false); }, [tab]);

  const selectRun = async item => {
    if (item.configuration?.model_id !== CNS_MODEL_ID) return;
    if (item.id === run?.id && !selecting) { showView('scene', run.id); return; }
    const sequence = ++selectionSequence.current;
    selectionRequest.current?.abort();
    const controller = new AbortController(); selectionRequest.current = controller; setSelecting(true);
    try {
      freshExperiment.current = false;
      setPlaying(false); setFieldPlayback(null); setFieldContactDraft(null); setFieldContactPick(null); setError(''); setTimeMs(0);
      const selected = await simulationApi.get(item.id, controller.signal);
      if (sequence !== selectionSequence.current) return;
      setRun(selected); setConfig(clone(selected.configuration)); setPlaying(selected.state === 'completed' && !prefersReducedMotion());
      if (selected.configuration.model_id === 'male-cns-hybrid-v1' && !fullCns) { setOpacity(.18); setLocalWindow(false); setShowResponse(false); }
      showView(tab, selected.id);
      draftPlacement.current = null; setPlacing(false); setPickingStimulus(false); setDrawer(false); pendingRequest.current = null;
    } catch { if (sequence === selectionSequence.current && !controller.signal.aborted) setError('Не удалось открыть опыт. Повторите выбор.'); }
    finally { if (sequence === selectionSequence.current) setSelecting(false); }
  };
  const retryComparison = async () => {
    const referenceId = initialComparisonId.current, selected = selectedId.current;
    if (!referenceId || !selected || retryingComparison) return;
    const sequence = selectionSequence.current;
    setRetryingComparison(true);
    try {
      const reference = comparisonReference(await simulationApi.get(referenceId));
      if (sequence !== selectionSequence.current || selectedId.current !== selected) return;
      if (!reference) { setError('Закреплённая запись A ещё не завершена. Опыт B открыт без сравнения.'); return; }
      setComparison(reference); setError(''); showView('comparison', selected, reference);
    } catch {
      if (sequence === selectionSequence.current && selectedId.current === selected) setError(COMPARISON_UNAVAILABLE);
    } finally { setRetryingComparison(false); }
  };
  const launch = async () => {
    if (pending || busy || selecting || placing || !config) return;
    if (electricalPrimary) {
      if (!primaryStimStatus.ready || !primaryStimForm.current) { setStimPanel(true); setDrawer(false); return; }
      setStimPanel(false); primaryStimForm.current.requestSubmit(); return;
    }
    setFieldPlayback(null); setFieldContactDraft(null); setFieldContactPick(null); setPickingStimulus(false);
    setPending(true); setError(''); setPlaying(false);
    const retained = comparison || (preview && recordingChanged ? comparisonReference(run) : null);
    if (retained && !comparison) setComparison(retained);
    const sequence = ++selectionSequence.current;
    const body = { title: model?.name || 'Опыт', configuration: config, parent_run_id: run?.id || null };
    const signature = JSON.stringify(body);
    if (pendingRequest.current?.signature !== signature) pendingRequest.current = { signature, payload: { ...body, request_id: uuid() } };
    try {
      const created = await simulationApi.create(pendingRequest.current.payload);
      if (sequence === selectionSequence.current) { setRun(created); selectedId.current = created.id; showView(tab, created.id, retained); }
      pendingRequest.current = null; await refreshRuns();
    } catch { if (sequence === selectionSequence.current) setError('Не удалось подтвердить запуск. Повторная попытка использует тот же ключ запроса.'); }
    finally { setPending(false); }
  };
  const update = (field, value) => setConfig(current => ({ ...current, [field]: value }));
  const position = (key, xyz) => setConfig(current => ({
    ...current, placement: updateContactPosition(current.placement, key, xyz),
  }));
  const openElectrodes = event => {
    setNativeView(false);
    setStimPanel(false);
    setPickingStimulus(false);
    if (placing) { setDrawer(true); return; }
    showView('scene');
    draftPlacement.current = clone(config.placement); placementInvoker.current = event?.currentTarget;
    const context = model.scene_context;
    if (!config.placement.registration && context) setConfig(current => ({ ...current, placement: { ...current.placement, mesh_asset_id: context.mesh_asset_id, registration: clone(context) } }));
    setPlacing(true); setDrawer(true); setPlaying(false); setLocalWindow(true); setFocusLocal(value => value + 1);
  };
  const cancelPlacement = useCallback(() => {
    const previous = draftPlacement.current; draftPlacement.current = null;
    if (previous) setConfig(current => ({ ...current, placement: previous }));
    setPlacing(false); setDrawer(false); setResetCamera(value => value + 1); (placementInvoker.current || settingsButton.current)?.focus();
  }, []);
  const openParameters = () => { setNociceptionOpen(false); if (placing) cancelPlacement(); setRecordingDetails(false); setPickingStimulus(false); if (electricalPrimary) { setDrawer(false); setStimPanel(true); } else { setStimPanel(false); setDrawer(true); } };
  const switchView = mode => {
    if (placing) cancelPlacement();
    if (mode !== 'scene') {
      setStimPanel(false); setPlaying(false);
      if (fieldContactPick) { setFieldContactDraft(fieldEditOriginal.current); fieldEditOriginal.current = null; setFieldContactPick(null); }
    }
    setPickingStimulus(false); showView(mode);
  };
  const toggleFullscreen = () => { if (!fullscreen.active) { if (placing) cancelPlacement(); setPickingStimulus(false); setDrawer(false); } fullscreen.toggle(); };
  useEffect(() => {
    if (!placing) return undefined;
    const cancel = event => { if (event.key === 'Escape') { event.preventDefault(); cancelPlacement(); } };
    window.addEventListener('keydown', cancel);
    return () => window.removeEventListener('keydown', cancel);
  }, [placing, cancelPlacement]);
  useEffect(() => {
    if (!fieldContactPick) return undefined;
    const cancel = event => {
      if (event.key !== 'Escape') return;
      event.preventDefault(); setFieldContactPick(null);
      setFieldContactDraft(fieldEditOriginal.current); fieldEditOriginal.current = null;
    };
    window.addEventListener('keydown', cancel);
    return () => window.removeEventListener('keydown', cancel);
  }, [fieldContactPick]);
  const geometry = model?.geometry || preview?.geometry;
  const contactError = config ? placementIssue(config.placement, geometry) : '';
  const validContact = Boolean(config && !contactError);
  const recordingChanged = preview && JSON.stringify(config) !== JSON.stringify(run.configuration);
  // Outside the editor, the visible electrodes must belong to the displayed
  // signal. The pending configuration is preserved for the next calculation.
  const scenePlacement = !placing && preview ? run.configuration.placement : config?.placement;
  const compareError = preview ? comparisonIssue(comparison, run?.configuration, run?.result?.manifest, preview) : '';
  const sceneCompareError = comparison && preview ? comparisonSceneIssue(comparison, run?.configuration) : '';
  const compatibleComparison = compareError || comparison?.run_id === run?.id ? null : comparison;
  const primaryTraceColor = comparison?.run_id === run?.id ? SIMULATION_TRACES.reference : SIMULATION_TRACES.current;
  const anchor = value => setConfig(current => current.placement.registration ? ({
    ...current, placement: { ...current.placement, registration: { ...current.placement.registration,
      surface_anchor: null, surface_anchors: { ...current.placement.registration.surface_anchors, [value.contact]: value } } },
  }) : current);
  const newExperience = async () => {
    const sequence = ++selectionSequence.current; selectionRequest.current?.abort();
    const controller = new AbortController(); selectionRequest.current = controller; setSelecting(true);
    const existing = run?.configuration?.model_id === CNS_MODEL_ID && run?.result?.preview?.connectome ? run : null;
    const saved = runs.find(item => item.configuration?.model_id === CNS_MODEL_ID && item.state === 'completed');
    let scene = existing;
    if (!scene && saved) {
      try {
        scene = await simulationApi.get(saved.id, controller.signal);
        if (!scene?.result?.preview?.connectome?.manifest_sha256) scene = null;
      }
      catch { if (!controller.signal.aborted) setError('Не удалось загрузить сцену ЦНС.'); }
    }
    if (!scene && !controller.signal.aborted) {
      try { scene = await simulationApi.sceneTemplate(controller.signal); }
      catch { if (!controller.signal.aborted) setError('Не удалось загрузить сцену ЦНС.'); }
    }
    if (controller.signal.aborted || sequence !== selectionSequence.current) return;
    const manifest = scene?.result?.preview?.connectome?.manifest_sha256;
    const preset = manifest && fieldDemoPreset(manifest);
    if (!scene || !preset) {
      setSelecting(false); setError('Нет доступной подготовленной сцены ЦНС. Выберите завершённый опыт ЦНС.'); return;
    }
    freshExperiment.current = true; fieldUserEdited.current = false;
    preparedFieldScene.current = scene.id;
    selectedId.current = scene.id; setRun(scene); setTab('scene'); setSearchParams({ run: scene.id }, { replace: true });
    setComparison(null); setFieldPlayback(null); setFieldContactDraft(null); setFieldDisplayNormals(null); setFieldContactPick(null); setTimeMs(0); setPlaying(false); setPlacing(false); setDrawer(false); setStimPanel(false);
    setError(''); setNotice('');
    pendingRequest.current = null; cameraLink.reset(); setResetCamera(value => value + 1);
    draftPlacement.current = null; fieldEditOriginal.current = null;
    const configuration = { graph_manifest_sha256: manifest, source_ids: [174827, 176609], seed: 1,
      simulation: { ...preset.simulation, allow_disconnected: true }, threshold_mv: -20, max_distance_um: 2 };
    setConfig(clone(scene.configuration)); setPickingStimulus(false); setOpacity(.18); setLocalWindow(false); setShowResponse(false);
    setFieldContactDraft({ sceneRunId: scene.id, kind: 'fragments', configuration,
      simulation: clone(configuration.simulation), changed: false, delivered: false });
    setFieldSnapRequest(value => value + 1); setSelecting(false);
  };

  if (!config) return <Flex h="full" align="center" justify="center" px={6}><Stack maxW="460px"><Text role={error ? 'alert' : 'status'}>{error || 'Подключение к вычислительному контуру…'}</Text>{error && <Button onClick={() => { setError(''); setConnectAttempt(value => value + 1); }}>Повторить подключение</Button>}</Stack></Flex>;

  const sceneControls = <><SceneVisibilityControls
    placing={placing} pickingStimulus={pickingStimulus} fieldContactPick={fieldContactPick}
    nativeView={nativeView} setNativeView={setNativeView} bodyVisible={bodyVisible}
    setBodyVisible={setBodyVisible} opacity={opacity} setOpacity={setOpacity} fullCns={displayedFullCns}
    localWindow={localWindow} setLocalWindow={setLocalWindow} neurons={neurons} setNeurons={setNeurons}
    regionsVisible={regionsVisible} setRegionsVisible={setRegionsVisible} electricalPrimary={electricalPrimary}
    activeField={activeField} openElectrodes={openElectrodes} busy={busy} />
    {displayedFullCns && <Button size="xs" variant="ghost" aria-pressed={nociceptionVisible} onClick={() => { setStimPanel(false); setDrawer(false); setRecordingDetails(false); setNociceptionVisible(!nociceptionVisible); setNociceptionOpen(!nociceptionVisible); }}>Ноцицепция</Button>}</>;

  return <Flex ref={fullscreen.root} position="relative" h="full" minH={0} bg={CHAT_THEME.pageBg} fontFamily={CHAT_FONT_FAMILY} color="white" overflow="hidden">
    {sidebar && !fullscreen.active && <SimulationSidebar history={history} modelId={CNS_MODEL_ID} selectedId={run?.id} onNew={newExperience} onSelect={selectRun} onClose={() => setSidebarChoice(false)} onRemove={async item => {
      await simulationApi.removeFromHistory(item.id);
      if (selectedId.current === item.id) {
        selectionSequence.current += 1; selectionRequest.current?.abort();
        setRun(null); setFieldPlayback(null); setFieldContactDraft(null); setComparison(null);
        setPlaying(false); setTimeMs(0); setSearchParams({}, { replace: true });
      }
      await refreshRuns();
    }} />}
    <Flex direction="column" flex={1} minW={0} minH={0}>
      <HStack as="header" minH="52px" px={3} borderBottom="1px solid" borderColor={CHAT_THEME.panelBorder} spacing={3}>
        <IconButton aria-label="Показать или скрыть список опытов" aria-expanded={sidebar} icon={<FiMenu />} size="sm" variant="ghost" onClick={() => setSidebarChoice(!sidebar)} />
        <Box w="7px" h="7px" bg={busy ? 'orange.300' : 'green.300'} borderRadius="full" />
        <Text fontWeight="600" fontSize="13px" flex={1} minW={0} noOfLines={1} display={{ base: 'none', lg: 'block' }}>{model?.name || 'Модель'}</Text>
        <HStack spacing={1} minW={0} flex={{ base: 1, lg: 'initial' }} overflowX="auto">{[['scene', 'Сцена'], ['comparison', 'Сравнение'], ['files', 'Файлы']].map(([id, title]) => <Tooltip key={id} label={id === 'comparison' && !comparison ? 'Закрепите завершённую запись кнопкой «Сравнить»' : undefined}><Button flexShrink={0} size="sm" isDisabled={id === 'comparison' && !comparison} variant={tab === id ? 'outline' : 'ghost'} onClick={() => switchView(id)}>{title}</Button></Tooltip>)}</HStack>
        <Tooltip label={fullscreen.active ? 'Выйти из полноэкранного режима' : 'Полноэкранный показ'}><IconButton aria-label={fullscreen.active ? 'Выйти из полноэкранного режима' : 'Полноэкранный показ'} icon={fullscreen.active ? <FiMinimize /> : <FiMaximize />} size="sm" variant="ghost" onClick={toggleFullscreen} /></Tooltip>
        {busy ? <Button size="sm" leftIcon={<FiSquare />} isDisabled={run.state === 'cancelling'} onClick={async () => { try { setRun(await simulationApi.cancel(run.id)); } catch { setError('Не удалось подтвердить остановку. Повторите запрос.'); } }}>Остановить</Button>
          : electricalPrimary && primaryStimStatus.running ? <Text fontSize="12px" color={CHAT_THEME.textSecondary}>Расчёт выполняется</Text>
          : <Button size="sm" leftIcon={<FiPlay />} bg={CHAT_THEME.primary} color="white" _hover={{ bg: CHAT_THEME.primary, opacity: .9 }} onClick={launch} isLoading={pending} isDisabled={!profileReady || (!electricalPrimary && !validContact) || selecting || placing || Boolean(fieldContactPick)}>Запустить</Button>}
      </HStack>
      {error && <Alert status="error" bg="rgba(120,32,44,.4)" py={2} fontSize="13px"><AlertIcon /><Text flex={1}>{error}</Text>{error === COMPARISON_UNAVAILABLE && initialComparisonId.current && <Button size="xs" mr={2} isLoading={retryingComparison} onClick={retryComparison}>Повторить загрузку A</Button>}<CloseButton onClick={() => setError('')} /></Alert>}
      <Box flex={1} minH={0} position="relative" display={tab === 'files' ? 'none' : 'block'}>
        {tab === 'comparison' && comparison ? <SimulationComparison reference={comparison} run={run} issue={compareError} sceneIssue={sceneCompareError}
          catalog={catalog} timeMs={timeMs} opacity={opacity} neurons={neurons} localWindow={localWindow}
          cameraLink={cameraLink} resetCamera={resetCamera} focusLocal={focusLocal} onMotorReadout={receiveMotorReadout} />
          : tab === 'scene' ? <SimulatorScene nativeView={nativeView} onNativeView={value => { setNativeView(value); if (value) setNeurons(true); }} onMotorReadout={receiveMotorReadout} onFieldEventsVerified={receiveFieldEvents} targetProbe={activeTarget} onShowTarget={target => { if (targetTimeline(activeField, target)) { setTargetPlayback(target); setTimeMs(0); setPlaying(false); } }} fullConnectome={displayedFullCns} opacity={opacity} neurons={neurons} placement={scenePlacement} onPlacement={position} placing={placing && !busy} preview={preview} fieldRun={sceneField} fieldSourceConfiguration={activeFieldConfig} fieldContactDraft={fieldContactDraft && fieldContactDraft.sceneRunId === run?.id ? fieldContactDraft.simulation : null} fieldContactNormals={fieldContactDraft?.normals || fieldDisplayNormals} fieldSnapRequest={fieldSnapRequest} onFieldContactsSnap={snapped => !fieldUserEdited.current && setFieldContactDraft(previous => previous && ({ ...previous, simulation: { ...previous.simulation, ...Object.fromEntries(Object.entries(snapped).map(([key, value]) => [key, value.coordinates])) }, normals: Object.fromEntries(Object.entries(snapped).map(([key, value]) => [key, value.normal])), changed: true, delivered: false }))} fieldContactPick={fieldContactPick} sceneControls={sceneControls} bodyVisible={bodyVisible} regionsVisible={regionsVisible} showNociceptionCandidates={nociceptionVisible} onFieldContactSelect={key => {
            if (!electricalPrimary || busy || primaryStimStatus.running) return;
            fieldUserEdited.current = true;
            fieldEditOriginal.current = fieldContactDraft ? clone(fieldContactDraft) : null;
            if (activeField && !fieldContactDraft) setFieldContactDraft({ fieldRunId: activeField.id, sceneRunId: run.id, kind: Array.isArray(activeFieldConfig?.source_ids) ? 'fragments' : 'field', configuration: clone(activeFieldConfig), simulation: clone(activeFieldConfig.simulation), normals: fieldDisplayNormals, changed: false });
            setFieldContactPick(key); setRegionsVisible(true); setOpacity(.18); setStimPanel(false); setDrawer(false); setNativeView(false); setTimeMs(0); setPlaying(false); setPickingStimulus(false);
          }} onFieldContactPick={(key, point, normal) => { setFieldContactDraft(previous => previous && ({ ...previous, simulation: { ...previous.simulation, [key]: point }, normals: { ...previous.normals, [key]: normal }, changed: true, delivered: false })); fieldEditOriginal.current = null; setFieldContactPick(null); }} runId={run?.id} pickingStimulus={pickingStimulus} onStimulusRegion={region => { const input = model.input_regions.find(item => item.id === region); if (!input || input.available === false) { setNotice('Сенсорный вход этой области недоступен для выбранной модели.'); return; } update('stimulus_region', region); setPickingStimulus(false); setNotice(region === 'notum' ? 'Выбрана вся сенсорная популяция спинной поверхности груди; точка воздействия не рассчитывается. Запустите расчёт.' : `Вход следующего опыта: ${input.name}. Запустите расчёт для новой записи.`); }} timeMs={timeMs} selectedContact={contact} onRegion={setNotice} resetCamera={resetCamera} modelGeometry={placing ? geometry : preview?.geometry || displayedModel.geometry} sceneContext={scenePlacement?.registration || (placing ? model.scene_context : displayedModel.scene_context)} onAnchor={anchor} focusLocal={focusLocal} invalidPlacement={placing && Boolean(contactError)} modelVisualization={displayedModel.visualization} localWindow={localWindow} cameraLink={cameraLink} /> : null}
        {(tab === 'scene' || tab === 'comparison') && <>
        <HStack position="absolute" top={3} left={3} right={3} pointerEvents="none" justify="space-between" align="start">
          {(tab === 'comparison' || !preview?.connectome) && <HStack pointerEvents="auto" bg="rgba(9,13,25,.9)" border="1px solid" borderColor={CHAT_THEME.panelBorder} borderRadius="6px" p={1} spacing={1}>{sceneControls}</HStack>}
          <HStack ml="auto" pointerEvents="auto"><Tooltip placement="left" label={displayedFullCns ? "Приблизить электроды" : "Приблизить локальную цепь"}><IconButton aria-label={displayedFullCns ? "Приблизить электроды" : "Приблизить локальную цепь"} icon={<FiZoomIn />} size="sm" onClick={() => { setNativeView(false); if (!displayedFullCns) setLocalWindow(true); setFocusLocal(value => value + 1); }} /></Tooltip><Tooltip placement="left" label="Центрировать камеру"><IconButton aria-label="Центрировать камеру" icon={<FiCrosshair />} size="sm" onClick={() => setResetCamera(value => value + 1)} /></Tooltip><IconButton ref={settingsButton} aria-label="Параметры модели" title="Параметры модели" icon={<FiSettings />} size="sm" onClick={openParameters} /></HStack>
        </HStack>
        <Box position="absolute" bottom={3} left={4} right={drawer ? '330px' : 4} pointerEvents="none">{fieldClearanceNotice && <Text role="status" fontSize="12px" color="#B6BECE">{fieldClearanceNotice}</Text>}{(tab === 'comparison' || contactError || !preview || placing || pickingStimulus) && <Text fontSize="12px" color={contactError ? 'red.200' : '#B6BECE'}>{tab === 'comparison' ? 'Общие время, камера и шкала E1−REF · окно меняет только отображение' : contactError || notice}</Text>}
          {!activeField && recordingChanged && <Text fontSize="11px" color="orange.200">{placing ? 'Положения в сцене — черновик; сигнал относится к сохранённому расчёту.' : 'Показаны электроды сохранённого расчёта; изменённые параметры будут использованы при следующем запуске.'}</Text>}
          </Box>
        </>}
        {nociceptionOpen && tab === 'scene' && <Box id="nociception-panel" as="section" aria-label="Ноцицептивная цепь" position="absolute" zIndex={3} right={3} top="58px" w={{ base: 'min(90vw, 400px)', lg: '420px' }} bg="rgba(10,14,28,.98)" border="1px solid" borderColor={CHAT_THEME.panelBorder} borderRadius="8px" p={4}>
          <HStack mb={3}><Text flex={1} fontWeight="600">Ноцицептивная цепь</Text><CloseButton aria-label="Закрыть сведения о ноцицепции" onClick={() => setNociceptionOpen(false)} /></HStack>
          <Text fontSize="13px" color="orange.200" fontWeight="600" mb={2}>Сопоставление нейронов не подтверждено</Text>
          <Text fontSize="13px" color={CHAT_THEME.textSecondary} mb={3}>Оранжевые кольца — предварительные соответствия 26 сенсорных нейронов, голубые — до 160 аннотированных восходящих клеток, получающих от них связи. Яркость меняется при событиях сохранённого расчёта. Соответствия и функция не подтверждены; это не полная цепь и не измерение боли.</Text>
          <Text as="a" href="https://pmc.ncbi.nlm.nih.gov/articles/PMC12636578/" target="_blank" rel="noopener noreferrer" fontSize="12px" color="blue.300">Исследование ноцицептивных путей ↗</Text>
        </Box>}
        {recordingDetails && tab === 'scene' && <Box as="section" aria-label="Сведения о записи" position="absolute" zIndex={3} right={3} top="58px" bottom={3} w={{ base: 'min(90vw, 400px)', lg: '420px' }} bg="rgba(10,14,28,.98)" border="1px solid" borderColor={CHAT_THEME.panelBorder} borderRadius="8px" overflowY="auto" p={4}>
          <HStack mb={4}><Text flex={1} fontWeight="600">Сведения о записи</Text><CloseButton aria-label="Закрыть сведения о записи" onClick={() => setRecordingDetails(false)} /></HStack>
          <Stack spacing={2} mb={4} fontSize="12px" color={CHAT_THEME.textSecondary}>
            {!activeField && preview?.connectome && <Text>Сенсорный вход: {preview.connectome.stimulus_region === 'thorax' ? 'популяции всех шести ног' : displayedModel.input_regions?.find(item => item.id === preview.connectome.stimulus_region)?.name || preview.connectome.stimulus_region}. E1 и REF регистрируют сигнал; движение условное.</Text>}
            {!activeField && preview?.connectome?.stimulus_region === 'notum' && <Text>Подсветка груди условно обозначает всю входную группу, а не точку воздействия.</Text>}
            {activeField && <><Text fontWeight="600" color="white">Обозначения</Text>
              <Text>Оранжевые метки обозначают пороговые переходы сегментов, а не спайки всей клетки.</Text>
              <Text>Цветная подсветка показывает разность состояния с контрольным расчётом: тёплый цвет — увеличение, синий — уменьшение. Значения до 0,1 % максимальной разности не выделяются. Это не измеренный потенциал и не спайки.</Text>
              <Text>Для разреженно сохранённых отсчётов показывается предыдущее значение; краткие изменения могут быть пропущены.</Text></>}
          </Stack>
          {activeField && <Stack spacing={2} mb={4} fontSize="12px" color="orange.200">
            {sceneField?.result?.manifest?.kind === 'experimental-field-proxy' && <Text>{fieldProxyExplanation(fieldPlayback?.direct)}</Text>}
            {sceneField?.result?.manifest?.kind === 'experimental-field-proxy' && fieldProxyActivityNotice(sceneField, verifiedProxyHistogram) && <Text>{fieldProxyActivityNotice(sceneField, verifiedProxyHistogram)}</Text>}
            {sceneField?.result?.manifest?.kind === 'experimental-field-proxy' && fieldExclusionNotice(sceneField.result.preview) && <Text>{fieldExclusionNotice(sceneField.result.preview)}</Text>}
            <Text>Модель не откалибрована; совмещение ЦНС и контактов с телом приблизительное. Движение условное.</Text>
            {activeField.result?.preview?.unresolved_candidates > 0 && <Text>Не сопоставлены синаптические позиции: {activeField.result.preview.unresolved_candidates}. Они не учтены.</Text>}
            {activeField.result?.preview?.kind === 'experimental-coupled-population' && <DiscretizationNotice geometry={activeField.result.preview.geometry_discretization} />}
            {activeField.result?.preview?.source_unresolved_graph_pairs > 0 && <Text>Не сопоставлены исходящие синапсы: {activeField.result.preview.source_unresolved_graph_pairs}. Их активность неизвестна и не включена в передачу.</Text>}
          </Stack>}
          {(activeField || fieldContactDraft) && <Text fontSize="12px" color={CHAT_THEME.textSecondary} mb={3}>Распознавание ниже относится к сохранённому сенсорному опыту. Для текущего электрического расчёта оно не выполнялось.</Text>}
          {preview && <Stack spacing={4} fontSize="13px">
            <RecognitionSummary preview={preview} stimulus={run.configuration.stimulus} regionName={displayedModel.input_regions?.find(item => item.id === run.configuration.stimulus_region)?.name} />
            {preview.connectome && <ReplayRecording sourceId={run.id} timeMs={replayTime} onTime={setReplayTime} />}
          </Stack>}
        </Box>}
        <Box as="section" aria-label="Электрическая стимуляция" display={stimPanel && tab === 'scene' ? 'block' : 'none'} position="absolute" zIndex={3} right={3} top="58px" bottom={3} w={{ base: 'min(90vw, 400px)', lg: '420px' }} bg="rgba(10,14,28,.98)" border="1px solid" borderColor={CHAT_THEME.panelBorder} borderRadius="8px" overflowY="auto" p={4}>
          <HStack mb={3}><Text flex={1} fontWeight="600">Электрическая стимуляция</Text><CloseButton aria-label="Закрыть STIM" onClick={() => setStimPanel(false)} /></HStack>
          <FieldRecordingModes formRef={primaryStimForm} onPrimaryStatus={updatePrimaryStimStatus} onClearanceNotice={setFieldClearanceNotice} onSourceForFiles={setFieldSourceForFiles} onFailure={() => setStimPanel(true)} canRestore={() => !fieldUserEdited.current && !freshExperiment.current} sceneRunId={preview?.connectome ? run?.id : null} sceneManifest={preview?.connectome?.manifest_sha256} sceneDescription={preview?.connectome} incomingContacts={fieldContactDraft && fieldContactDraft.sceneRunId === run?.id && !fieldContactDraft.delivered && !fieldContactPick ? fieldContactDraft : null} onConsumeContacts={consumeFieldContacts} onAdjustContact={(draft, key) => {
            fieldUserEdited.current = true;
            setFieldContactDraft(previous => {
              const normals = key ? { ...(previous?.normals || fieldDisplayNormals || {}) } : {}; if (key) delete normals[key];
              return { ...draft, sceneRunId: run.id, normals, changed: true, delivered: true };
            });
            setFieldContactPick(null); setPlaying(false); setTimeMs(0);
          }} onAdjustParameters={draft => {
            fieldUserEdited.current = true;
            setFieldContactDraft(previous => ({ ...draft, sceneRunId: run.id,
              normals: previous?.normals || fieldDisplayNormals, changed: true, delivered: true }));
            setFieldContactPick(null); setPlaying(false); setTimeMs(0);
          }} onPlaceContacts={draft => {
            fieldEditOriginal.current = fieldContactDraft ? clone(fieldContactDraft) : null;
            setFieldContactDraft({ ...draft, sceneRunId: run.id, normals: fieldContactDraft?.normals, changed: false, delivered: false }); setFieldContactPick('source_um'); setStimPanel(false); setDrawer(false); setNativeView(false); setPlaying(false); setPickingStimulus(false); showView('scene', run.id, null);
          }} onShowOnBody={(field, options) => {
            if (options?.restore && fieldUserEdited.current) return;
            if (options?.direct) {
              const simulation = options.simulation;
              if (!directFieldMatchesScene(field, simulation, run.id, preview?.connectome?.manifest_sha256)) {
                setError('Сетевой результат не соответствует параметрам опыта.'); return;
              }
              setFieldDisplayNormals(contactNormalsForSimulation(fieldContactDraft, simulation));
              setFieldContactDraft(null); setFieldContactPick(null);
              setFieldPlayback({ sceneRunId: run.id, run: field, direct: true,
                source: { configuration: { simulation, graph_manifest_sha256: field.configuration.graph_manifest_sha256 } } });
              setTimeMs(0); setPlaying(!prefersReducedMotion()); setShowResponse(true); setStimPanel(false);
              setNeurons(true); showView('scene', run.id, null); return;
            }
            const fieldData = field.result?.preview?.timeline || field.result?.preview;
            const source = options?.source || null, sourceConfig = source?.configuration || field.configuration;
            if ((source && field.parent_run_id !== source.id) || (source?.parent_run_id && source.parent_run_id !== run.id)
                || field.configuration?.graph_manifest_sha256 !== preview?.connectome?.manifest_sha256
                || sourceConfig?.graph_manifest_sha256 !== field.configuration?.graph_manifest_sha256
                || !fieldData?.time_ms?.length || !Array.isArray(fieldData.neural_uv) || !sourceConfig?.simulation) return;
            const candidateProxy = options?.proxy;
            const stimulusKeys = ['source_um', 'return_um', 'current_na', 'conductivity_s_m', 'clearance_um', 'coordinate_frame'];
            const validProxy = candidateProxy?.state === 'completed' && candidateProxy.parent_run_id === source?.id
              && candidateProxy.result?.manifest?.kind === 'experimental-field-proxy'
              && candidateProxy.result?.preview?.recording === null
              && candidateProxy.configuration?.graph_manifest_sha256 === sourceConfig.graph_manifest_sha256
              && candidateProxy.result?.preview?.duration_ms === sourceConfig.simulation.duration_ms
              && stimulusKeys.every(key => JSON.stringify(candidateProxy.configuration?.[key]) === JSON.stringify(sourceConfig.simulation[key]));
            if (!options?.restore) freshExperiment.current = false;
            setFieldDisplayNormals(contactNormalsForSimulation(fieldContactDraft, sourceConfig.simulation));
            setFieldContactDraft(null); setFieldContactPick(null); setFieldPlayback({ sceneRunId: run.id, run: field, source, proxy: validProxy ? candidateProxy : null }); setTimeMs(0); setPlaying(!options?.restore && !prefersReducedMotion()); setShowResponse(true); setComparison(null); setDrawer(false); setStimPanel(false); setNeurons(true); setOpacity(.18); showView('scene', run.id, null);
            if (candidateProxy && !validProxy) setError('Сетевой результат не соответствует параметрам записи и не показан.');
          }} />
        </Box>
        {drawer && <Box as="section" aria-labelledby="simulation-settings-title" position="absolute" right={3} top="58px" bottom={3} w={{ base: '280px', lg: '310px' }} bg="rgba(10,14,28,.98)" border="1px solid" borderColor={CHAT_THEME.panelBorder} borderRadius="8px" overflowY="auto" p={4} onKeyDown={e => { if (e.key === 'Escape' && !placing) setDrawer(false); }}>
          <HStack mb={4}><Text id="simulation-settings-title" flex={1} fontWeight="600">{placing ? 'Записывающие контакты' : 'Модель и параметры'}</Text><CloseButton aria-label="Закрыть параметры" onClick={() => placing ? cancelPlacement() : setDrawer(false)} /></HStack>
          {placing ? <Stack spacing={4}>
            <Text fontSize="12px" color={CHAT_THEME.textSecondary}>Локальная внеклеточная регистрация. Контакт должен находиться вне нейронных источников.</Text>
            <ButtonGroup size="sm" isAttached>{[['electrode', 'E1'], ['reference', 'REF']].map(([id, name]) => <Button key={id} variant={contact === id ? 'solid' : 'outline'} onClick={() => setContact(id)}>{name}</Button>)}</ButtonGroup>
            {['x_um', 'y_um', 'z_um'].map(axis => <FormControl key={axis} isInvalid={Boolean(contactError)}><FormLabel htmlFor={`contact-${contact}-${axis}`} fontSize="12px">{axis[0].toUpperCase()}, мкм</FormLabel><Input id={`contact-${contact}-${axis}`} aria-describedby={contactError ? 'placement-issue' : undefined} type="number" min={-500} max={500} step={5} size="sm" value={config.placement[contact][axis]} onChange={event => position(contact, { ...config.placement[contact], [axis]: event.target.value === '' ? '' : Number(event.target.value) })} /></FormControl>)}
            {contactError && <Text id="placement-issue" role="alert" color="red.200" fontSize="12px">{contactError}</Text>}
            <Text fontSize="11px" color={CHAT_THEME.textSecondary}>Клик по доступной поверхности груди устанавливает центр контакта на 25 мкм снаружи неё. Координаты можно уточнить вручную. E1 и REF не создают воздействие.</Text>
            <Button size="sm" bg={CHAT_THEME.primary} color="white" _hover={{ bg: CHAT_THEME.primary, opacity: .9 }} isDisabled={!validContact} onClick={() => { draftPlacement.current = null; setPlacing(false); setDrawer(false); setNotice('Положение применено к следующему опыту. Для новой записи запустите расчёт.'); }}>Применить</Button>
            <Button size="sm" variant="outline" onClick={cancelPlacement}>Отмена</Button>
          </Stack> : <Stack spacing={5} as="form" noValidate onSubmit={e => e.preventDefault()}>
            <FormControl><FormLabel fontSize="12px">Расчётная модель</FormLabel><AppSelect ariaLabel="Расчётная модель" value={config.model_id} isDisabled={busy}
              options={catalog.models.filter(item => item.id === CNS_MODEL_ID).map(item => ({ value: item.id, label: item.name, isDisabled: item.available === false }))}
              onChange={value => { const next = catalog.models.find(item => item.id === value); if (!next) return; setConfig(clone(next.defaults)); setPickingStimulus(false); setOpacity(next.id === 'male-cns-hybrid-v1' ? .18 : 1); setLocalWindow(next.id !== 'male-cns-hybrid-v1'); }} /></FormControl>
            {fullCns && <FormControl><FormLabel fontSize="12px">Сенсорный вход</FormLabel><AppSelect ariaLabel="Сенсорный вход" value={config.stimulus_region} isDisabled={busy}
              options={model.input_regions.map(item => ({ value: item.id, label: sensoryInputName(item.id, model.input_regions) + (item.available === false ? ' · тактильный вход не определён' : ''), isDisabled: item.available === false }))} onChange={value => update('stimulus_region', value)} />
              <Text fontSize="11px" color={CHAT_THEME.textSecondary} mt={2}>Модельный тактильный вход; интенсивность не является температурой или мерой боли. Брюшные сенсорные клетки входят в сеть, но тактильная популяция для этого пресета не определена.</Text>
              {config.stimulus_region === 'notum' && <Text fontSize="11px" color={CHAT_THEME.textSecondary} mt={2}>Выбрана вся аннотированная популяция спинной поверхности груди. Точка воздействия и электрическое поле не рассчитываются.</Text>}</FormControl>}
            <FormControl><FormLabel fontSize="12px">Модельное воздействие</FormLabel><ButtonGroup size="xs" isAttached>{[['none', 'Нет'], ['weak', 'Слабое'], ['strong', 'Сильное']].map(([id, name]) => <Button key={id} variant={config.stimulus === id ? 'solid' : 'outline'} onClick={() => update('stimulus', id)}>{name}</Button>)}</ButtonGroup></FormControl>
            <Range label="Возбудимость модели" min={0.7} max={1.3} value={config.excitability} onChange={value => update('excitability', value)} />
            <Range label="Адаптация модели" value={config.adaptation} onChange={value => update('adaptation', value)} />
            <FormControl><FormLabel htmlFor="simulation-seed" fontSize="12px">Seed</FormLabel><Input id="simulation-seed" type="number" size="sm" min={0} step={1} value={config.seed} onChange={e => update('seed', Number(e.target.value))} /></FormControl>
            <Text fontSize="12px" color={CHAT_THEME.textSecondary}>Длительность {config.duration_ms} мс · шаг локальной модели {config.dt_ms} мс{fullCns ? ' · шаг полной сети 1 мс' : ''}. Однородный проводник: {config.conductivity_s_m} См/м. Шум записи: {config.noise_uv} мкВ.</Text>
            {fullCns && <Text fontSize="11px" color={CHAT_THEME.textSecondary}>Рассчитываются все 25,6 млн связей. Для рисунка показывается до 24 000. E1−REF регистрирует шесть локальных HH-компонентов, возбуждаемых популяциями VNC; это не потенциал всей нервной системы. Распознавание проверено отдельно для этого пресета и доступно только в пределах проверенных условий.</Text>}
            <Text fontSize="11px" color={CHAT_THEME.textSecondary}>Параметры задаются для следующего запуска. Зарегистрированная конфигурация опыта сохраняется.</Text>
            <Text fontSize="11px">NEURON · Hodgkin–Huxley · LFPy. Параметры мембраны не откалиброваны по Drosophila. Модель не оценивает субъективную боль.</Text>
          </Stack>}
        </Box>}
      </Box>
      {tab === 'files' && <SimulationFiles scene={run} playback={fieldPlayback} target={targetPlayback} sourceForFiles={fieldSourceForFiles} busy={busy} />}
      {electricalPrimary && primaryStimStatus.running && tab === 'scene' ? <SimulationProgress stage={primaryStimStatus.stage} phase={primaryStimStatus.phase} progress={primaryStimStatus.progress} connectionLost={primaryStimStatus.connectionLost} reducedMotion={reducedMotion} onCancel={primaryStimStatus.cancel} canCancel={primaryStimStatus.canCancel} /> : electricalPrimary && fieldContactDraft && !activeField && tab === 'scene' ? <Box as="section" aria-label="Ожидание расчёта" borderTop="1px solid" borderColor={CHAT_THEME.panelBorder} px={4} py={3} bg="rgba(6,9,18,.98)"><Text fontSize="13px" fontWeight="600">Запись появится после расчёта</Text><Text fontSize="12px" color={CHAT_THEME.textSecondary} mt={1}>Разместите электроды и запустите опыт.</Text></Box> : <Box as="section" aria-label={activeField ? 'Воспроизведение электрического расчёта' : 'Воспроизведение основного опыта'} borderTop="1px solid" borderColor={CHAT_THEME.panelBorder} px={3} pt={2} pb={2} bg="rgba(6,9,18,.98)">
        <HStack justify="space-between" fontSize="12px" mb={1}><HStack><FiActivity /><Text fontWeight="600">{activeTarget ? `E1 − REF · ${activeTarget.source_cells} клеток + цель ${activeTarget.target_id}` : activeField ? fieldResultHeading(activeField, fieldPlayback?.direct) : fieldContactDraft ? 'E1 − REF · ожидание расчёта' : displayedFullCns ? "E1 − REF · 6 локальных моделей" : "Запись E1 − REF"}</Text>{activeTarget && <Button size="xs" variant="ghost" onClick={() => setTargetPlayback(null)}>Исходная запись</Button>}{!activeField && !fieldContactDraft && <Button size="xs" variant="ghost" display={fullscreen.active ? 'none' : 'inline-flex'} aria-pressed={showResponse} onClick={() => setShowResponse(value => !value)}>Вход и ответ</Button>}</HStack><Text fontSize="11px" noOfLines={1} color={!activeField && recordingChanged ? 'orange.200' : CHAT_THEME.textSecondary}>{activeTarget ? (activeTarget.timing_mode === 'upper_bound' ? 'Запись: верхняя граница интервала · анимация сети: модель LIF' : activeTarget.timing_mode === 'lower_bound' ? 'Запись: нижняя граница интервала · анимация сети: модель LIF' : 'Запись: односторонний физический повтор · анимация сети: модель LIF') : activeField ? fieldResultDescription(activeField, fieldPlayback?.direct) : fieldContactDraft ? 'Результат для текущего положения контактов ещё не рассчитан' : recordingChanged ? 'Черновик параметров · запись сохранённого расчёта' : preview ? `Воспроизведение сохранённого расчёта${playing && loop ? ' · повтор' : ''}` : 'Ожидание записи'}</Text></HStack>
        {comparison && !compareError && <HStack fontSize="11px" spacing={4}><Text color={SIMULATION_TRACES.reference}>A · закреплённая запись</Text>{compatibleComparison && <><Text color={SIMULATION_TRACES.current}>B · выбранный опыт</Text>{showResponse && !fullscreen.active && <Text color={CHAT_THEME.textSecondary}>Вход, спайки и движение — B</Text>}</>}</HStack>}
        {activeField && <HStack spacing={3} mb={1}>{sceneField?.result?.manifest?.kind === 'experimental-field-proxy' && <Text fontSize="11px" color={CHAT_THEME.textSecondary}>{fieldPlayback?.direct ? 'Упрощённая сеть · запись E1–REF не рассчитана' : 'Сеть: упрощённая модель · запись: выбранные клетки'}</Text>}{(sceneField?.result?.manifest?.kind === 'experimental-field-proxy' ? verifiedProxyHistogram?.every(value => value === 0) : activeField.result?.preview?.network_spikes === 0) && <Text fontSize="11px" color={CHAT_THEME.textSecondary}>Сетевых спайков: 0</Text>}<Button size="xs" variant="ghost" color="orange.200" onClick={() => { setStimPanel(false); setDrawer(false); setNociceptionOpen(false); setRecordingDetails(true); }}>Ограничения модели</Button></HStack>}
        <SignalPlot motorReadout={fieldContactDraft ? null : motorReadout} preview={playbackPreview} timeMs={timeMs} onTime={value => { setPlaying(false); setTimeMs(value); }} comparison={activeField || fieldContactDraft ? null : compatibleComparison} showResponse={!fieldContactDraft && showResponse && !fullscreen.active} modelVisualization={displayedModel.visualization} primaryColor={primaryTraceColor} />
        {compareError && <Text fontSize="11px" color="orange.200">{compareError}</Text>}
        <HStack spacing={3} fontSize="11px"><IconButton aria-label={playing ? 'Пауза записи' : 'Воспроизвести запись'} size="xs" icon={playing ? <FiPause /> : <FiPlay />} isDisabled={!playbackPreview || Boolean(fieldContactPick)} onClick={() => { if (timeMs >= playbackPreview?.time_ms.at(-1)) setTimeMs(0); setPlaying(value => !value); }} /><Text minW="65px">{timeMs.toFixed(1)} мс</Text><input aria-label="Время воспроизведения" disabled={Boolean(fieldContactPick)} type="range" min={0} max={playbackPreview?.time_ms.at(-1) || 200} step={0.025} value={timeMs} onChange={e => { setPlaying(false); setTimeMs(Number(e.target.value)); }} style={{ flex: 1, accentColor: '#2D5BFF' }} />
          <Box w="116px" flexShrink={0}><AppSelect size="xs" isSearchable={false} ariaLabel="Скорость воспроизведения" value={playbackRate} onChange={setPlaybackRate} options={[{ value: '0.001', label: '0,001×' }, { value: '0.002', label: '0,002×' }, { value: '0.005', label: '0,005×' }, { value: '0.01', label: '0,01×' }, { value: '0.02', label: '0,02×' }, { value: '0.05', label: '0,05×' }, { value: '0.1', label: '0,1×' }, { value: '0.2', label: '0,2×' }, { value: '0.5', label: '0,5×' }, { value: '1', label: '1×' }]} /></Box>
          <Tooltip label="Циклическое воспроизведение рассчитанной записи"><IconButton aria-label="Повторять запись" aria-pressed={loop} size="xs" variant={loop ? 'outline' : 'ghost'} icon={<FiRepeat />} isDisabled={!preview} onClick={() => setLoop(value => !value)} /></Tooltip>
          {!activeField && !fieldContactDraft && preview?.prediction && <Text noOfLines={1}>Распознано{compatibleComparison ? ' B' : ''}: {labels[preview.prediction.class]}</Text>}
          {preview && tab === 'scene' && <Button size="xs" variant="ghost" aria-expanded={recordingDetails} onClick={() => { setStimPanel(false); setDrawer(false); setNociceptionOpen(false); setRecordingDetails(value => !value); }}>Сведения о записи</Button>}
          {!electricalPrimary && <Button size="xs" variant="ghost" isDisabled={!preview || placing} onClick={() => { setPlaying(false); const next = comparison ? null : comparisonReference(run); setComparison(next); showView(next ? 'comparison' : 'scene', run.id, next); setNotice(comparison ? 'Сравнение отключено.' : 'Запись A закреплена. Выберите другой завершённый опыт слева.'); }}>{comparison ? 'Убрать сравнение' : 'Сравнить'}</Button>}
        </HStack>
      </Box>}
    </Flex>
  </Flex>;
}
