import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert, AlertIcon, Box, Button, ButtonGroup, CloseButton, Flex, FormControl, FormLabel,
  HStack, IconButton, Input, Stack, Text, Tooltip, usePrefersReducedMotion,
} from '@chakra-ui/react';
import { FiActivity, FiCrosshair, FiDownload, FiFile, FiFolder, FiMaximize, FiMenu, FiMinimize, FiPause, FiPlay, FiPlus, FiRepeat, FiSettings, FiSquare, FiZoomIn } from 'react-icons/fi';
import { BiTestTube } from 'react-icons/bi';
import { useSearchParams } from 'react-router-dom';
import { SIMULATION_THEME as CHAT_THEME, SIMULATION_FONT_FAMILY as CHAT_FONT_FAMILY, SIMULATION_TRACES } from './theme';
import { simulationApi } from './api';
import SignalPlot from './SignalPlot';
import RecognitionSummary from './RecognitionSummary';
import SimulatorScene from './SimulatorScene';
import SimulationComparison from './SimulationComparison';
import { createCameraLink } from './sceneCamera';
import useSimulationHistory from './useSimulationHistory';
import useSimulationArtifacts from './useSimulationArtifacts';
import useSimulationFullscreen from './useSimulationFullscreen';
import { placementIssue, comparisonIssue, comparisonSceneIssue, comparisonReference } from './sceneModel';
import { useAppToast } from '@shared/hooks/useAppToast';
import { prefersReducedMotion } from '../../utils/motion';
import AppSelect from '@shared/controls/AppSelect';

const states = { queued: 'В очереди', preparing: 'Подготовка', running: 'Расчёт', publishing: 'Сохранение', completed: 'Завершён', cancelling: 'Остановка', cancelled: 'Остановлен', failed: 'Ошибка' };
const labels = { none: 'Нет воздействия', weak: 'Слабое воздействие', strong: 'Сильное воздействие' };
const busyStates = new Set(['queued', 'preparing', 'running', 'publishing', 'cancelling']);
const NETWORK_WARNING = 'Связь прервана. Опыт сохранён; восстановление соединения…';
const clone = value => JSON.parse(JSON.stringify(value));
const uuid = () => crypto.randomUUID();
const defaultModel = catalog => catalog.models.find(model => model.id === catalog.default_model_id) || catalog.models[0];

function Range({ label, value, onChange, min = 0, max = 1, step = 0.05 }) {
  return <FormControl>
    <HStack justify="space-between" mb={2}><FormLabel m={0} fontSize="13px">{label}</FormLabel><Text fontSize="12px" color={CHAT_THEME.textSecondary}>{Number(value).toFixed(2)}</Text></HStack>
    <input type="range" aria-label={label} min={min} max={max} step={step} value={value}
      onChange={event => onChange(Number(event.target.value))} style={{ width: '100%', accentColor: '#2D5BFF', cursor: 'pointer' }} />
  </FormControl>;
}

export default function SimulatorPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const initialRunId = useRef(searchParams.get('run'));
  const initialComparisonId = useRef(searchParams.get('compare'));
  const initialComparisonView = useRef(searchParams.get('view') === 'comparison');
  const [catalog, setCatalog] = useState(null), [config, setConfig] = useState(null);
  const [run, setRun] = useState(null);
  const history = useSimulationHistory(), { runs, replace: replaceHistory, refresh: refreshRuns } = history;
  const [tab, setTab] = useState('scene'), [sidebar, setSidebar] = useState(true);
  const [drawer, setDrawer] = useState(false), [placing, setPlacing] = useState(false);
  const [contact, setContact] = useState('electrode'), [opacity, setOpacity] = useState(1);
  const [neurons, setNeurons] = useState(true), [resetCamera, setResetCamera] = useState(0);
  const [focusLocal, setFocusLocal] = useState(0);
  const [localWindow, setLocalWindow] = useState(true);
  const [pickingStimulus, setPickingStimulus] = useState(false);
  const cameraLink = useMemo(createCameraLink, []);
  const [pending, setPending] = useState(false), [error, setError] = useState('');
  const fullscreen = useSimulationFullscreen(setError);
  const [selecting, setSelecting] = useState(false), [connectAttempt, setConnectAttempt] = useState(0);
  const [notice, setNotice] = useState('Выберите грудную область для локальной модели регистрации.');
  const [timeMs, setTimeMs] = useState(0), [playing, setPlaying] = useState(false);
  const [loop, setLoop] = useState(true);
  const [showResponse, setShowResponse] = useState(true);
  const [comparison, setComparison] = useState(null), [profileReady, setProfileReady] = useState(false);
  const toast = useAppToast(), draftPlacement = useRef(null), pendingRequest = useRef(null), settingsButton = useRef(null);
  const selectionSequence = useRef(0), placementInvoker = useRef(null);
  const selectionRequest = useRef(null);
  const reducedMotion = usePrefersReducedMotion();
  const selectedId = useRef(null); selectedId.current = run?.id;
  const renderedVersion = useRef(''); renderedVersion.current = run?.updated_at || '';
  const busy = busyStates.has(run?.state), preview = run?.result?.preview;
  const model = catalog?.models.find(item => item.id === config?.model_id) || catalog?.models[0];
  const displayedModel = preview ? catalog?.models.find(item => item.id === run?.configuration.model_id) || model : model;
  const fullCns = config?.model_id === 'male-cns-hybrid-v1';
  const artifacts = useSimulationArtifacts(run?.id, run?.state, tab === 'files'), { files } = artifacts;
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
        let selected;
        if (initialRunId.current) {
          selected = await simulationApi.get(initialRunId.current, controller.signal);
        }
        let reference = null, comparisonWarning = '';
        if (initialComparisonId.current) {
          try {
            reference = comparisonReference(initialComparisonId.current === selected?.id ? selected
              : await simulationApi.get(initialComparisonId.current, controller.signal));
            if (!reference) comparisonWarning = 'Закреплённая запись A ещё не завершена. Опыт B открыт без сравнения.';
          } catch {
            comparisonWarning = 'Закреплённая запись A недоступна. Опыт B открыт без сравнения.';
          }
        }
        if (controller.signal.aborted) return;
        replaceHistory(list); setCatalog(result); setConfig(clone(selected?.configuration || defaultModel(result).defaults));
        if ((selected?.configuration || defaultModel(result).defaults).model_id === 'male-cns-hybrid-v1') { setOpacity(.18); setLocalWindow(false); setShowResponse(false); setNotice('Выберите сенсорный вход в параметрах или кнопкой «Область воздействия».'); }
        setComparison(reference); setTab(reference && initialComparisonView.current ? 'comparison' : 'scene');
        if (comparisonWarning) setError(comparisonWarning);
        if (selected) { setRun(selected); setPlaying(selected.state === 'completed' && !prefersReducedMotion()); }
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
      else if (fresh.state === 'failed') setError(`Расчёт не завершён: ${fresh.error || 'проверьте параметры и повторите опыт'}`);
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
    if (!playing || !preview) return undefined;
    let frame, previous;
    const tick = now => {
      const elapsed = previous ? Math.min(now - previous, 100) : 0; previous = now;
      setTimeMs(value => {
        const next = value + elapsed * 0.05;
        if (next >= preview.time_ms.at(-1)) { if (loop) return next % preview.time_ms.at(-1); setPlaying(false); return preview.time_ms.at(-1); }
        return next;
      });
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, preview, loop]);
  useEffect(() => { if (reducedMotion) setPlaying(false); }, [reducedMotion]);
  useEffect(() => { if (tab === 'files') setPlaying(false); }, [tab]);

  const selectRun = async item => {
    const sequence = ++selectionSequence.current;
    selectionRequest.current?.abort();
    const controller = new AbortController(); selectionRequest.current = controller; setSelecting(true);
    try {
      setPlaying(false); setError(''); setTimeMs(0);
      const selected = await simulationApi.get(item.id, controller.signal);
      if (sequence !== selectionSequence.current) return;
      setRun(selected); setConfig(clone(selected.configuration)); setPlaying(selected.state === 'completed' && !prefersReducedMotion());
      if (selected.configuration.model_id === 'male-cns-hybrid-v1' && !fullCns) { setOpacity(.18); setLocalWindow(false); setShowResponse(false); }
      showView(tab, selected.id);
      draftPlacement.current = null; setPlacing(false); setPickingStimulus(false); setDrawer(false); pendingRequest.current = null;
    } catch { if (sequence === selectionSequence.current && !controller.signal.aborted) setError('Не удалось открыть опыт. Повторите выбор.'); }
    finally { if (sequence === selectionSequence.current) setSelecting(false); }
  };
  const launch = async () => {
    if (pending || busy || selecting || placing || !config) return;
    setPickingStimulus(false);
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
  const position = (key, xyz) => setConfig(current => ({ ...current, placement: { ...current.placement, [key]: xyz } }));
  const openElectrodes = event => {
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
  const openParameters = () => { if (placing) cancelPlacement(); setPickingStimulus(false); setDrawer(true); };
  const switchView = mode => { if (placing) cancelPlacement(); setPickingStimulus(false); showView(mode); };
  const toggleFullscreen = () => { if (!fullscreen.active) { if (placing) cancelPlacement(); setPickingStimulus(false); setDrawer(false); } fullscreen.toggle(); };
  useEffect(() => {
    if (!placing) return undefined;
    const cancel = event => { if (event.key === 'Escape') { event.preventDefault(); cancelPlacement(); } };
    window.addEventListener('keydown', cancel);
    return () => window.removeEventListener('keydown', cancel);
  }, [placing, cancelPlacement]);
  const geometry = model?.geometry || preview?.geometry;
  const contactError = config ? placementIssue(config.placement, geometry) : '';
  const validContact = Boolean(config && !contactError);
  const recordingChanged = preview && JSON.stringify(config) !== JSON.stringify(run.configuration);
  const compareError = preview ? comparisonIssue(comparison, run?.configuration, run?.result?.manifest, preview) : '';
  const sceneCompareError = comparison && preview ? comparisonSceneIssue(comparison, run?.configuration) : '';
  const compatibleComparison = compareError || comparison?.run_id === run?.id ? null : comparison;
  const primaryTraceColor = comparison?.run_id === run?.id ? SIMULATION_TRACES.reference : SIMULATION_TRACES.current;
  const anchor = value => setConfig(current => current.placement.registration ? ({ ...current, placement: { ...current.placement, registration: { ...current.placement.registration, surface_anchor: value } } }) : current);
  const newExperience = () => {
    selectionSequence.current += 1; selectionRequest.current?.abort(); setSelecting(false);
    selectedId.current = null; setRun(null); setTab('scene'); setSearchParams({}, { replace: true });
    setComparison(null); setTimeMs(0); setPlaying(false); setPlacing(false); setDrawer(false);
    setError(''); setNotice('Выберите грудную область для локальной модели регистрации.');
    pendingRequest.current = null; cameraLink.reset(); setResetCamera(value => value + 1);
    draftPlacement.current = null;
    const next = defaultModel(catalog);
    setConfig(clone(next.defaults)); setPickingStimulus(false);
    if (next.id === 'male-cns-hybrid-v1') { setOpacity(.18); setLocalWindow(false); setShowResponse(false); setNotice('Выберите сенсорный вход в параметрах или кнопкой «Область воздействия».'); }
  };

  if (!config) return <Flex h="full" align="center" justify="center" px={6}><Stack maxW="460px"><Text role={error ? 'alert' : 'status'}>{error || 'Подключение к вычислительному контуру…'}</Text>{error && <Button onClick={() => { setError(''); setConnectAttempt(value => value + 1); }}>Повторить подключение</Button>}</Stack></Flex>;

  return <Flex ref={fullscreen.root} h="full" minH={0} bg={CHAT_THEME.pageBg} fontFamily={CHAT_FONT_FAMILY} color="white" overflow="hidden">
    {sidebar && !fullscreen.active && <Flex as="aside" aria-label="Опыты" w={{ base: '180px', lg: '260px' }} flexShrink={0} direction="column" bg={CHAT_THEME.sidebarBg} borderRight="1px solid" borderColor={CHAT_THEME.panelBorder} p={3}>
      <Text fontSize="11px" color="#7B9DFF" letterSpacing=".16em" fontWeight="600" mb={3}>ОПЫТЫ</Text>
      <Button leftIcon={<FiPlus />} variant="outline" colorScheme="blue" justifyContent="start" size="sm" onClick={newExperience}>Новый опыт</Button>
      <Stack mt={4} spacing={1} overflowY="auto" flex={1}>
        {!runs.length && <Text fontSize="12px" color={CHAT_THEME.textSecondary} p={2}>Сохранённых опытов пока нет</Text>}
        {runs.map(item => <Button key={item.id} data-run-id={item.id} size="sm" variant="ghost" h="auto" minH="48px" justifyContent="start" whiteSpace="normal" leftIcon={<BiTestTube />} bg={item.id === run?.id ? CHAT_THEME.panelActive : undefined} onClick={() => selectRun(item)}>
          <Box textAlign="left"><Text fontSize="13px">{labels[item.configuration?.stimulus] || item.title || 'Опыт'}</Text><Text fontSize="11px" color={CHAT_THEME.textSecondary}>{states[item.state] || item.state} · {new Date(item.created_at).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}</Text></Box>
        </Button>)}
        {history.error && <Text role="alert" fontSize="12px" color="red.200">{history.error}</Text>}
        {(history.nextOffset !== null || history.error) && <Button size="sm" variant="outline" isLoading={history.loading} onClick={history.error ? history.retry : history.more}>{history.error ? 'Повторить загрузку опытов' : 'Ещё опыты'}</Button>}
      </Stack>
      <Button variant="ghost" size="sm" leftIcon={<FiFolder />} justifyContent="start" onClick={() => switchView('files')}>Файлы опыта</Button>
      <Button variant="ghost" size="sm" leftIcon={<FiSettings />} justifyContent="start" onClick={openParameters}>Параметры</Button>
    </Flex>}
    <Flex direction="column" flex={1} minW={0} minH={0}>
      <HStack as="header" minH="52px" px={3} borderBottom="1px solid" borderColor={CHAT_THEME.panelBorder} spacing={3}>
        <IconButton aria-label="Показать или скрыть список опытов" icon={<FiMenu />} size="sm" variant="ghost" onClick={() => setSidebar(value => !value)} />
        <Box w="7px" h="7px" bg={busy ? 'orange.300' : 'green.300'} borderRadius="full" />
        <Text fontWeight="600" fontSize="13px" flex={1} noOfLines={1}>{model?.name || 'Модель'}</Text>
        <HStack spacing={1} display={{ base: 'none', md: 'flex' }}>{[['scene', 'Сцена'], ['comparison', 'Сравнение'], ['recording', 'Запись'], ['files', 'Файлы']].map(([id, title]) => <Tooltip key={id} label={id === 'comparison' && !comparison ? 'Закрепите завершённую запись кнопкой «Сравнить»' : undefined}><Button size="sm" isDisabled={id === 'comparison' && !comparison} variant={tab === id ? 'outline' : 'ghost'} onClick={() => switchView(id)}>{title}</Button></Tooltip>)}</HStack>
        <Tooltip label={fullscreen.active ? 'Выйти из полноэкранного режима' : 'Полноэкранный показ'}><IconButton aria-label={fullscreen.active ? 'Выйти из полноэкранного режима' : 'Полноэкранный показ'} icon={fullscreen.active ? <FiMinimize /> : <FiMaximize />} size="sm" variant="ghost" onClick={toggleFullscreen} /></Tooltip>
        {busy ? <Button size="sm" leftIcon={<FiSquare />} isDisabled={run.state === 'cancelling'} onClick={async () => { try { setRun(await simulationApi.cancel(run.id)); } catch { setError('Не удалось подтвердить остановку. Повторите запрос.'); } }}>Остановить</Button>
          : <Button size="sm" leftIcon={<FiPlay />} bg={CHAT_THEME.primary} color="white" _hover={{ bg: CHAT_THEME.primary, opacity: .9 }} onClick={launch} isLoading={pending} isDisabled={!profileReady || !validContact || selecting || placing}>Запустить</Button>}
      </HStack>
      {error && <Alert status="error" bg="rgba(120,32,44,.4)" py={2} fontSize="13px"><AlertIcon /><Text flex={1}>{error}</Text><CloseButton onClick={() => setError('')} /></Alert>}
      <Box flex={1} minH={0} position="relative" display={tab === 'files' ? 'none' : 'block'}>
        {tab === 'comparison' && comparison ? <SimulationComparison reference={comparison} run={run} issue={compareError} sceneIssue={sceneCompareError}
          catalog={catalog} timeMs={timeMs} opacity={opacity} neurons={neurons} localWindow={localWindow}
          cameraLink={cameraLink} resetCamera={resetCamera} focusLocal={focusLocal} />
          : tab === 'scene' ? <SimulatorScene opacity={opacity} neurons={neurons} placement={config.placement} onPlacement={position} placing={placing && !busy} preview={preview} runId={run?.id} pickingStimulus={pickingStimulus} onStimulusRegion={region => { const input = model.input_regions.find(item => item.id === region); if (input?.available === false) { setNotice('Для брюшка не зарегистрирован тактильный вход. Выберите голову или ногу.'); return; } update('stimulus_region', region); setPickingStimulus(false); setNotice(`Вход следующего опыта: ${input?.name || region}. Запустите расчёт для новой записи.`); }} timeMs={timeMs} selectedContact={contact} onRegion={setNotice} resetCamera={resetCamera} modelGeometry={geometry} sceneContext={config.placement.registration || model.scene_context} onAnchor={anchor} focusLocal={focusLocal} invalidPlacement={Boolean(contactError)} modelVisualization={displayedModel.visualization} localWindow={localWindow} cameraLink={cameraLink} /> : null}
        {(tab === 'scene' || tab === 'comparison') && <>
        <HStack position="absolute" top={3} left={3} right={3} pointerEvents="none" justify="space-between" align="start">
          <HStack pointerEvents="auto" bg="rgba(9,13,25,.9)" border="1px solid" borderColor={CHAT_THEME.panelBorder} borderRadius="6px" p={1} spacing={1}>
            <Tooltip label="Прозрачное тело: показать нервную систему"><Button size="xs" variant="ghost" aria-pressed={opacity < .5} onClick={() => setOpacity(value => value >= .5 ? fullCns ? .18 : .24 : 1)}>Тело</Button></Tooltip>
            <Tooltip label="Окно отображения локальной цепи; расчёт не меняется"><Button aria-label="Окно локальной цепи" aria-pressed={localWindow} size="xs" variant={localWindow ? 'outline' : 'ghost'} onClick={() => setLocalWindow(value => !value)}>Окно</Button></Tooltip>
            <Button size="xs" variant={neurons ? 'outline' : 'ghost'} onClick={() => setNeurons(value => !value)}>Нейроны</Button>
            {fullCns && <Button size="xs" variant={pickingStimulus ? 'outline' : 'ghost'} aria-pressed={pickingStimulus} isDisabled={busy || placing} onClick={() => { setPickingStimulus(value => !value); setNotice('Нажмите на голову, брюшко или ногу для выбора сенсорного входа следующего опыта.'); }}>Область воздействия</Button>}
            <Button size="xs" variant={placing ? 'outline' : 'ghost'} onClick={openElectrodes} isDisabled={busy}>Электроды</Button>
            <Box px={2} w="110px" display={{ base: 'none', lg: 'block' }}><input aria-label="Прозрачность тела" type="range" min="0.12" max="1" step="0.01" value={opacity} onChange={e => setOpacity(Number(e.target.value))} style={{ width: '100%', accentColor: '#2D5BFF' }} /></Box>
          </HStack>
          <HStack pointerEvents="auto"><Tooltip label="Приблизить локальную цепь"><IconButton aria-label="Приблизить локальную цепь" icon={<FiZoomIn />} size="sm" onClick={() => { setLocalWindow(true); setFocusLocal(value => value + 1); }} /></Tooltip><Tooltip label="Центрировать камеру"><IconButton aria-label="Центрировать камеру" icon={<FiCrosshair />} size="sm" onClick={() => setResetCamera(value => value + 1)} /></Tooltip><Tooltip label="Параметры модели"><IconButton ref={settingsButton} aria-label="Параметры модели" icon={<FiSettings />} size="sm" onClick={openParameters} /></Tooltip></HStack>
        </HStack>
        <Box position="absolute" bottom={3} left={4} right={drawer ? '330px' : 4} pointerEvents="none"><Text fontSize="12px" color={contactError ? 'red.200' : '#B6BECE'}>{tab === 'comparison' ? 'Общие время, камера и шкала E1−REF · окно меняет только отображение' : contactError || notice}</Text><Text fontSize="11px" color="#8792AA">{preview?.connectome ? `MaleCNS · 166 700 нейронов · ${preview.connectome.active_neurons.toLocaleString('ru-RU')} активны в опыте · зелёный: спайки · пунктир: схема периферических нервов` : fullCns && !preview ? 'Полная нервная система появится после расчёта · периферические пути схематичны' : 'Авторская локальная цепь · спайки: зелёный · реакция тела условная'}</Text></Box>
        </>}
        {tab === 'recording' && <Box position="absolute" inset={0} bg={CHAT_THEME.pageBg} overflowY="auto" p={6}>
          <Text fontSize="18px" fontWeight="600" mb={3}>Запись и распознавание воздействия</Text>
          {!preview && <Text color={CHAT_THEME.textSecondary}>Запустите опыт или выберите завершённый в списке слева.</Text>}
          {preview && <Stack spacing={4}>
            <SignalPlot preview={preview} timeMs={timeMs} onTime={setTimeMs} comparison={compatibleComparison} primaryColor={primaryTraceColor} />
            <RecognitionSummary preview={preview} stimulus={run.configuration.stimulus} regionName={displayedModel.input_regions?.find(item => item.id === run.configuration.stimulus_region)?.name} />
          </Stack>}
        </Box>}
        {drawer && <Box as="section" aria-labelledby="simulation-settings-title" position="absolute" right={3} top="58px" bottom={3} w={{ base: '280px', lg: '310px' }} bg="rgba(10,14,28,.98)" border="1px solid" borderColor={CHAT_THEME.panelBorder} borderRadius="8px" overflowY="auto" p={4} onKeyDown={e => { if (e.key === 'Escape' && !placing) setDrawer(false); }}>
          <HStack mb={4}><Text id="simulation-settings-title" flex={1} fontWeight="600">{placing ? 'Положение электрода' : 'Модель и параметры'}</Text><CloseButton aria-label="Закрыть параметры" onClick={() => placing ? cancelPlacement() : setDrawer(false)} /></HStack>
          {placing ? <Stack spacing={4}>
            <Text fontSize="12px" color={CHAT_THEME.textSecondary}>Локальная внеклеточная регистрация. Контакт должен находиться вне нейронных источников.</Text>
            <ButtonGroup size="sm" isAttached>{[['electrode', 'E1'], ['reference', 'REF']].map(([id, name]) => <Button key={id} variant={contact === id ? 'solid' : 'outline'} onClick={() => setContact(id)}>{name}</Button>)}</ButtonGroup>
            {['x_um', 'y_um', 'z_um'].map(axis => <FormControl key={axis} isInvalid={Boolean(contactError)}><FormLabel htmlFor={`contact-${contact}-${axis}`} fontSize="12px">{axis[0].toUpperCase()}, мкм</FormLabel><Input id={`contact-${contact}-${axis}`} aria-describedby={contactError ? 'placement-issue' : undefined} type="number" min={-500} max={500} step={5} size="sm" value={config.placement[contact][axis]} onChange={event => position(contact, { ...config.placement[contact], [axis]: event.target.value === '' ? '' : Number(event.target.value) })} /></FormControl>)}
            {contactError && <Text id="placement-issue" role="alert" color="red.200" fontSize="12px">{contactError}</Text>}
            <Text fontSize="11px" color={CHAT_THEME.textSecondary}>Клик на теле выбирает область; эти координаты задают физический контакт локальной модели.</Text>
            <Button size="sm" bg={CHAT_THEME.primary} color="white" _hover={{ bg: CHAT_THEME.primary, opacity: .9 }} isDisabled={!validContact} onClick={() => { draftPlacement.current = null; setPlacing(false); setDrawer(false); setNotice('Положение применено к следующему опыту. Для новой записи запустите расчёт.'); }}>Применить</Button>
            <Button size="sm" variant="outline" onClick={cancelPlacement}>Отмена</Button>
          </Stack> : <Stack spacing={5} as="form" noValidate onSubmit={e => e.preventDefault()}>
            <FormControl><FormLabel fontSize="12px">Расчётная модель</FormLabel><AppSelect ariaLabel="Расчётная модель" value={config.model_id} isDisabled={busy}
              options={catalog.models.map(item => ({ value: item.id, label: item.name, isDisabled: item.available === false }))}
              onChange={value => { const next = catalog.models.find(item => item.id === value); if (!next) return; setConfig(clone(next.defaults)); setPickingStimulus(false); setOpacity(next.id === 'male-cns-hybrid-v1' ? .18 : 1); setLocalWindow(next.id !== 'male-cns-hybrid-v1'); }} /></FormControl>
            {fullCns && <FormControl><FormLabel fontSize="12px">Сенсорный вход</FormLabel><AppSelect ariaLabel="Сенсорный вход" value={config.stimulus_region} isDisabled={busy}
              options={model.input_regions.map(item => ({ value: item.id, label: item.name + (item.available === false ? ' · вход не зарегистрирован' : ''), isDisabled: item.available === false }))} onChange={value => update('stimulus_region', value)} />
              <Text fontSize="11px" color={CHAT_THEME.textSecondary} mt={2}>Модельный тактильный вход; интенсивность не является температурой или мерой боли.</Text></FormControl>}
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
      {tab === 'files' && <Box as="section" aria-labelledby="simulation-files-title" flex={1} overflowY="auto" p={6}>
        <HStack justify="space-between" mb={4}><Text id="simulation-files-title" fontWeight="600">Файлы выбранного опыта</Text>
          <Button size="sm" variant="outline" leftIcon={<FiDownload />} isDisabled={run?.state !== 'completed'} onClick={async () => { try { await simulationApi.downloadManifest(run.id); } catch { toast({ status: 'error', title: 'Манифест недоступен. Повторите скачивание.' }); } }}>Манифест</Button>
        </HStack>
        {!run && <Text color={CHAT_THEME.textSecondary}>Выберите опыт в списке слева.</Text>}
        {run && run.state !== 'completed' && <Text color={CHAT_THEME.textSecondary}>{busy ? 'Расчёт ещё не сохранён. Файлы появятся после завершения.' : 'У этого опыта нет опубликованных результатов.'}</Text>}
        {artifacts.loading && <Text role="status">Загрузка файлов опыта…</Text>}
        {artifacts.error && <Stack><Text role="alert">{artifacts.error}</Text><Button alignSelf="start" variant="outline" size="sm" onClick={artifacts.retry}>Повторить загрузку файлов</Button></Stack>}
        {run?.state === 'completed' && !artifacts.loading && !artifacts.error && !files.length && <Text color={CHAT_THEME.textSecondary}>Для этого опыта файлы не зарегистрированы.</Text>}
        {files.map(file => <HStack key={file.id} borderBottom="1px solid" borderColor={CHAT_THEME.panelBorder} py={3}><FiFile /><Box flex={1}><Text fontSize="13px">{file.name}</Text><Text fontSize="11px" color={CHAT_THEME.textSecondary}>{Math.ceil(file.bytes / 1024)} КБ · SHA-256 {file.sha256.slice(0, 12)}…</Text></Box><IconButton size="sm" aria-label={`Скачать ${file.name}`} icon={<FiDownload />} onClick={async () => { try { await simulationApi.download(run.id, file); } catch { toast({ status: 'error', title: 'Файл недоступен. Повторите скачивание.' }); } }} /></HStack>)}
      </Box>}
      <Box borderTop="1px solid" borderColor={CHAT_THEME.panelBorder} px={3} pt={2} pb={2} bg="rgba(6,9,18,.98)">
        <HStack justify="space-between" fontSize="12px" mb={1}><HStack><FiActivity /><Text fontWeight="600">Запись E1 − REF</Text><Button size="xs" variant="ghost" display={fullscreen.active ? 'none' : 'inline-flex'} aria-pressed={showResponse} onClick={() => setShowResponse(value => !value)}>Вход и ответ</Button></HStack><Text fontSize="11px" noOfLines={1} color={recordingChanged ? 'orange.200' : CHAT_THEME.textSecondary}>{recordingChanged ? 'Черновик параметров · запись сохранённого опыта' : preview ? `Воспроизведение сохранённого расчёта${playing && loop ? ' · повтор' : ''}` : 'Ожидание записи'}</Text></HStack>
        {comparison && !compareError && <HStack fontSize="11px" spacing={4}><Text color={SIMULATION_TRACES.reference}>A · закреплённая запись</Text>{compatibleComparison && <><Text color={SIMULATION_TRACES.current}>B · выбранный опыт</Text>{showResponse && !fullscreen.active && <Text color={CHAT_THEME.textSecondary}>Вход, спайки и движение — B</Text>}</>}</HStack>}
        <SignalPlot preview={preview} timeMs={timeMs} onTime={value => { setPlaying(false); setTimeMs(value); }} comparison={compatibleComparison} showResponse={showResponse && !fullscreen.active} modelVisualization={displayedModel.visualization} primaryColor={primaryTraceColor} />
        {compareError && <Text fontSize="11px" color="orange.200">{compareError}</Text>}
        <HStack spacing={3} fontSize="11px"><IconButton aria-label={playing ? 'Пауза записи' : 'Воспроизвести запись'} size="xs" icon={playing ? <FiPause /> : <FiPlay />} isDisabled={!preview} onClick={() => { if (timeMs >= preview?.time_ms.at(-1)) setTimeMs(0); setPlaying(value => !value); }} /><Text minW="105px">{timeMs.toFixed(1)} мс · 0,05×</Text><input aria-label="Время воспроизведения" type="range" min={0} max={preview?.time_ms.at(-1) || 200} step={0.025} value={timeMs} onChange={e => { setPlaying(false); setTimeMs(Number(e.target.value)); }} style={{ flex: 1, accentColor: '#2D5BFF' }} />
          <Tooltip label="Циклическое воспроизведение рассчитанной записи"><IconButton aria-label="Повторять запись" aria-pressed={loop} size="xs" variant={loop ? 'outline' : 'ghost'} icon={<FiRepeat />} isDisabled={!preview} onClick={() => setLoop(value => !value)} /></Tooltip>
          {preview?.prediction && <Text noOfLines={1}>Распознано{compatibleComparison ? ' B' : ''}: {labels[preview.prediction.class]}</Text>}
          {preview?.prediction_status && !preview.prediction && <Text title={preview.prediction_status.reason} fontSize="11px" noOfLines={1}>Распознавание недоступно · подробнее в «Запись»</Text>}
          <Button size="xs" variant="ghost" isDisabled={!preview || placing} onClick={() => { setPlaying(false); const next = comparison ? null : comparisonReference(run); setComparison(next); showView(next ? 'comparison' : 'scene', run.id, next); setNotice(comparison ? 'Сравнение отключено.' : 'Запись A закреплена. Выберите другой завершённый опыт слева.'); }}>{comparison ? 'Убрать сравнение' : 'Сравнить'}</Button>
        </HStack>
      </Box>
    </Flex>
  </Flex>;
}
