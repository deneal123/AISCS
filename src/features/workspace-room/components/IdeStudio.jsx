import { useEffect, useRef, useState } from 'react';
import { Box, Button, Flex, HStack, Icon, Text, useMediaQuery } from '@chakra-ui/react';
import AppSelect from '@shared/controls/AppSelect';
import AppLoading from '@shared/controls/AppLoading';
import { FiCode, FiFileText, FiFolder, FiGitBranch, FiPlus, FiRefreshCw, FiSave, FiClock, FiTerminal } from '@shared/icons';
import { colors, documentControls } from '@theme/tokens';
import { useIdeRepositories } from '../model/useIdeRepositories';
import { useIdeRepositoryReads } from '../model/useIdeRepositoryReads';
import { WorkspaceTree } from './WorkspaceTree';
import IdeCodePane from './IdeCodePane';
import IdeProjectStart from './IdeProjectStart';
import { useIdeSetup } from '../model/useIdeSetup';
import { useIdeEditor } from '../model/useIdeEditor';
import IdeCreateFileDialog from './IdeCreateFileDialog';
import IdeCloneDialog from './IdeCloneDialog';
import IdeMoveFileDialog from './IdeMoveFileDialog';
import { useIdeGit } from '../model/useIdeGit';
import IdeAgentPane from './IdeAgentPane';
import { useIdeEntry } from '../model/useIdeEntry';
import { IDE_CLONE_NOTICES, useIdeIsolatedClone } from '../model/useIdeIsolatedClone';
import { useIdeCloneRecovery } from '../model/useIdeCloneRecovery';
import IdeCloneRecoveryBar from './IdeCloneRecoveryBar';
import { useWorkbenchSplit } from '../model/usePdfSplit';
import IdeRuntimeStatus from './IdeRuntimeStatus';
import IdeMoveFileButton from './IdeMoveFileButton';
import IdeProjectHistory from './IdeProjectHistory';
import IdeProjectRecovery from './IdeProjectRecovery';
import IdeConsole from './IdeConsole';
import IdeStatusNotices from './IdeStatusNotices';
import { useIdeConsole } from '../model/useIdeConsole';
import { useIdeSavedProjects } from '../model/useIdeSavedProjects';
import './IdeStudio.css';

function ReadNotice({ children, onRetry }) {
  return <Flex p={4} gap={3} align="start" direction="column" role={onRetry ? 'alert' : undefined}>
    <Text fontSize="sm" color={colors.fg[3]}>{children}</Text>
    {onRetry && <Button size="document" variant="workbenchSecondary" onClick={onRetry}>Повторить чтение</Button>}
  </Flex>;
}


/** Repo-owned scene. The retained WorkHub owns only PDF/Library, never this tree. */
export default function IdeStudio({ threadId, active = true, onDirtyChange, onRegisterDraftLifecycle, onRequestNavigation, onThreadUnavailable, assistantRef, onContextChange, assistantRunning = false }) {
  const [wide] = useMediaQuery('(min-width: 1100px)');
  const split = useWorkbenchSplit('x', 50, { namespace: 'ide', label: 'Ширина кода и агента' });
  const treeSplit = useWorkbenchSplit('x', 30, { namespace: 'ide.tree', label: 'Ширина дерева файлов и кода', min: 20, max: 60 });
  const consoleSplit = useWorkbenchSplit('y', 70, { namespace: 'ide.console', label: 'Высота редактора и консоли', min: 30, max: 80 });
  const [consoleOpen, setConsoleOpen] = useState(true);
  const consoleTrigger = useRef(null);
  const historyTrigger = useRef(null);
  const historyReturnFocus = useRef(null);
  const separatorStyle = { w: '6px', cursor: 'col-resize', sx: { touchAction: 'none' }, bg: colors.border.subtle,
    _hover: { bg: colors.blue[500] }, _focusVisible: { outline: `2px solid ${colors.border.focus}`, outlineOffset: '-2px' } };
  const repositories = useIdeRepositories({ threadId, active, onThreadUnavailable });
  const [pane, setPane] = useState('files');
  const [creating, setCreating] = useState(false);
  const refreshAfterPreparation = useRef(null);
  const entry = useIdeEntry({ threadId, repositoryId: repositories.selectedId, active: active && !creating,
    registryReady: repositories.status === 'ready' && !repositories.loading && !repositories.error,
    blocked: assistantRunning, onAccepted: repositories.accept, onPrepared: () => refreshAfterPreparation.current?.() });
  const repositoryActive = active && !entry.waiting && !entry.error;
  const reads = useIdeRepositoryReads({ threadId, repositoryId: repositories.selectedId, active: repositoryActive });
  refreshAfterPreparation.current = reads.load;
  const [fileDialog, setFileDialog] = useState('');
  const [cloneOpen, setCloneOpen] = useState(false);
  const [moveFile, setMoveFile] = useState(null);
  const [treeSelection, setTreeSelection] = useState(null);
  const [treeMoveFeedback, setTreeMoveFeedback] = useState(false);
  const dialogContext = `${threadId}:${repositories.selectedId}:${reads.tree?.generation}`;
  const [dialogOwner, setDialogOwner] = useState('');
  useEffect(() => { setFileDialog(''); setCloneOpen(false); setMoveFile(null); setTreeSelection(null); setTreeMoveFeedback(false); }, [dialogContext]);
  const recovery = useIdeCloneRecovery({ threadId, repositoryId: repositories.selectedId,
    active: active && !creating && repositories.status === 'ready' && !repositories.error,
    onCompleted: attempt => { if (attempt.repository.repository_id === repositories.selectedId && !editor.file && !git.busy) void reads.load({ fresh: true }); } });
  const isolatedClone = useIdeIsolatedClone({ threadId, repositoryId: repositories.selectedId, active,
    onRecorded: () => recovery.refresh(),
    onCloned: item => { editor.discard(); repositories.accept(item); setPane('files'); } });
  const git = useIdeGit({ threadId, repositoryId: repositories.selectedId, generation: reads.tree?.generation, active: repositoryActive && reads.validated && !entry.awaitingReady,
    onCloneConflict: isolatedClone.run,
    onChanged: () => { editor.discard(); void reads.load(); } });
  const editor = useIdeEditor({ threadId, repositoryId: repositories.selectedId, generation: reads.tree?.generation, active,
    verified: repositoryActive && reads.validated && reads.runtime?.state === 'ready',
    onRecovered: reads.acceptRead,
    onMoved: value => { reads.acceptMove(value); setTreeSelection(null); },
    onDirtyChange, onRegisterDraftLifecycle, onWritten: (result, content) => { reads.acceptWrite(result, content); if (result.kind === 'file') setPane('code'); } });
  const resumeEntry = entry.resume;
  useEffect(() => {
    if (entry.awaitingReady && reads.validated && reads.runtime?.state === 'ready' && !assistantRunning) resumeEntry();
  }, [entry.awaitingReady, reads.validated, reads.runtime?.state, assistantRunning, resumeEntry]);
  const cloneDestinationPending = recovery.attempt?.repository.repository_id === repositories.selectedId
    && ['preparing', 'running', 'blocked'].includes(recovery.attempt?.state);
  const saved = useIdeSavedProjects({ threadId, repositoryId: repositories.selectedId,
    active: repositoryActive && !creating, generation: reads.tree?.generation,
    blocked: Boolean(editor.file || editor.busy || git.busy || isolatedClone.busy || assistantRunning || cloneDestinationPending || entry.waiting || entry.awaitingReady || entry.error),
    onRestored: () => { editor.discard(); void reads.load({ fresh: true }); } });
  const openHistory = event => { historyReturnFocus.current = event.currentTarget; saved.show(); };
  const closeHistory = () => {
    if (!historyReturnFocus.current?.isConnected) historyReturnFocus.current = historyTrigger.current;
    saved.close();
  };
  const terminal = useIdeConsole({ threadId, repositoryId: repositories.selectedId, generation: reads.tree?.generation,
    watching: assistantRunning,
    active, available: repositoryActive && reads.validated && reads.runtime?.state === 'ready',
    blocked: Boolean(editor.busy || saved.busy || git.busy || isolatedClone.busy || assistantRunning || entry.awaitingReady || cloneDestinationPending),
    onChanged: () => { if (!editor.file) void reads.load({ fresh: true }); } });
  const agentBlocked = Boolean(terminal.busy || saved.busy || entry.waiting || entry.awaitingReady || entry.error || !reads.validated || editor.file || editor.busy || git.busy || isolatedClone.busy || recovery.loading || recovery.error || cloneDestinationPending || reads.loading || reads.error || reads.runtime?.state !== 'ready');
  const agentContextKey = `${repositories.selectedId}:${repositories.selected?.name}:${reads.tree?.generation}:${agentBlocked}`;
  const wasRunning = useRef(false);
  useEffect(() => {
    if (active && wasRunning.current && !assistantRunning && !editor.file && !git.busy) void reads.load({ fresh: true });
    if (active || assistantRunning) wasRunning.current = assistantRunning;
  }, [active, assistantRunning]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (active) onContextChange?.(reads.tree && repositories.selectedId ? {
      thread_id: threadId, repository_id: repositories.selectedId, generation: reads.tree.generation, blocked: agentBlocked,
      name: repositories.selected?.name, refresh: () => { if (!editor.file) void reads.load({ fresh: true }); },
    } : null);
  }, [active, agentContextKey, onContextChange]); // eslint-disable-line react-hooks/exhaustive-deps
  const guard = (action, reading = false) => { if ((!terminal.busy || (reading && terminal.busy === 'agent')) && !saved.busy && !editor.busy && !git.busy && !isolatedClone.busy && (!assistantRunning || reading)) { if (onRequestNavigation) onRequestNavigation(action); else if (!editor.dirty) action(); } };
  const openClone = (fresh = false) => guard(() => {
    const attempt = recovery.attempt;
    if (recovery.loading || recovery.error) return;
    if (!fresh && attempt?.request && attempt.state !== 'complete') {
      if (!isolatedClone.restore(attempt)) return;
    } else if (!isolatedClone.fresh()) return;
    setDialogOwner(dialogContext); setCloneOpen(true);
  });
  const openCreate = (operation) => guard(() => { setDialogOwner(dialogContext); setFileDialog(operation); });
  const moveBlocked = !repositoryActive || !reads.validated || reads.runtime?.state !== 'ready' || Boolean(terminal.busy || editor.busy || saved.busy || git.busy || isolatedClone.busy || assistantRunning);
  const openMove = (item = reads.file) => { if (!moveBlocked) guard(() => { if (item?.path) { setTreeMoveFeedback(false); setDialogOwner(dialogContext); setMoveFile(item); } }); };
  const moveInTree = (item, destination) => guard(() => {
    setTreeMoveFeedback(true);
    const cached = reads.files?.find(file => file.path === item.path);
    void editor.move(cached ? { ...cached, type: item.type } : item, destination);
  });
  const setup = useIdeSetup({ threadId, repositoryId: repositories.selectedId, active,
    onCreated: (item) => { repositories.accept(item); setCreating(false); setPane('files'); }, onStarted: reads.load });
  const codeRef = useRef(null);
  const [focusRequest, setFocusRequest] = useState(null);
  useEffect(() => {
    if (!focusRequest) return;
    if (active && focusRequest.repositoryId === repositories.selectedId && focusRequest.path === reads.file?.path) codeRef.current?.focus();
    setFocusRequest(null);
  }, [active, focusRequest, repositories.selectedId, reads.file?.path]);
  const initial = Boolean(threadId) && ['idle', 'loading'].includes(repositories.status) && !repositories.items.length;
  const openFile = async (path, options) => {
    const repositoryId = repositories.selectedId;
    if (await reads.open(path, options)) { setPane('code'); setFocusRequest({ repositoryId, path }); }
  };
  const selectFile = (path) => { if (path === editor.file?.path) editor.editorRef.current?.focus(); else guard(() => { editor.discard(); void openFile(path); }, true); };
  const refresh = () => {
    if (saved.busy || editor.busy || git.busy || isolatedClone.busy || assistantRunning) return;
    // An observation is not navigation or permission to discard local source.
    // Keep registry selection pinned while an editor owns a recoverable copy.
    if (editor.file) { void reads.load(); return; }
    void repositories.load();
    if (repositories.selectedId) void reads.load({ fresh: true });
  };
  const guardedReads = { ...reads, open: (path, options) => { if (!options?.refresh && path === reads.file?.path) return reads.open(path, options);
    guard(() => { editor.discard(); void openFile(path, options); }, true); }, close: (path) => guard(() => { if (path === editor.file?.path) editor.discard(); reads.close(path); }, true) };
  const cloneView = isolatedClone.locked && !recovery.loading && !recovery.error && recovery.attempt?.intent_id === isolatedClone.request?.intent_id
    ? { ...isolatedClone, result: recovery.attempt, error: IDE_CLONE_NOTICES[recovery.attempt.state] || isolatedClone.error } : isolatedClone;
  const notices = [
    repositories.error && repositories.items.length > 0 && { id: 'registry', label: 'Не удалось получить список репозиториев. Сохранённые данные не заменены пустым списком.', onRetry: () => repositories.load(repositories.failedOffset) },
    reads.error && { id: 'runtime', label: 'Не удалось прочитать среду. Ранее загруженные исходники остаются доступными.', onRetry: reads.load },
    reads.observationExpired && { id: 'observation', label: 'Подготовка среды ещё не подтверждена. Новая среда автоматически не создаётся.', onRetry: reads.load },
    reads.fileError && { id: 'file', label: 'Не удалось открыть файл. Ранее загруженный текст не потерян.', onRetry: () => selectFile(reads.requestedPath) },
    git.error && !cloneOpen && { id: 'git', label: git.error, onRetry: () => { void git.run('status'); } },
    entry.gitWarning && !git.data?.initialized && { id: 'git-init', label: 'Среда подготовлена, но инициализация Git не подтверждена.', onRetry: () => { void git.run('status'); } },
    ['start', 'start_unavailable'].includes(setup.error) && { id: 'start', label: 'Запуск среды не подтверждён. Проект сохранён; повторная среда автоматически не создаётся.', onRetry: reads.load },
    !reads.loading && !reads.error && (reads.runtime?.state === 'not_created' || reads.runtime?.canRetry) && { id: 'start-action', label: 'Среда проекта не запущена.', onRetry: setup.start, action: 'Запустить среду' },
  ].filter(Boolean);
  const cloneNotice = recovery.error || (recovery.attempt && !(recovery.attempt.state === 'complete' && !recovery.completed));
  const activity = git.busy ? (git.busy === 'clone' ? 'Клонирую репозиторий…' : git.busy === 'init' ? 'Инициализирую Git…' : 'Читаю состояние Git…') : git.outcome || (setup.busy === 'start' ? 'Запускаю отдельную среду…' : '');
  return <Flex data-testid="ide-studio" display={active ? 'flex' : 'none'} flex="1" minW={0} minH={0} direction="column" bg={colors.bg.page}>
    <Flex as="section" aria-label="Репозиторий IDE" px={3} py={2} gap={2} align="center" flexWrap="wrap" flexShrink={0}
      sx={{ containerType: 'inline-size', containerName: 'ide-toolbar' }}
      borderBottom="1px solid" borderColor={colors.border.subtle}>
      <HStack spacing={2} minW={0} flex={{ base: '1 0 100%', md: 1 }}>
        <Icon as={FiCode} boxSize={4} color={colors.fg[3]} />
        <Box flex="1" minW={0} maxW="320px">
          <AppSelect size="document" ariaLabel="Репозиторий IDE" value={repositories.selectedId}
            placeholder={initial ? 'Загружаю репозитории…' : 'Выберите репозиторий'}
            options={repositories.items.map((item) => ({ value: item.repository_id, label: item.name }))}
            isSearchable={false} isDisabled={!repositories.items.length || Boolean(terminal.busy || saved.busy || entry.waiting || setup.busy || editor.busy || git.busy || isolatedClone.busy || assistantRunning)} onChange={(value) => guard(() => { editor.discard(); repositories.select(value); setCreating(false); setPane('files'); })} />
        </Box>
        {repositories.selected && !creating && !initial && !entry.waiting && !entry.error
          && <IdeRuntimeStatus runtime={reads.runtime} loading={reads.loading} />}
      </HStack>
      {!creating && !entry.waiting && !entry.error && reads.tree && reads.runtime?.state === 'ready' && (wide || pane === 'files') && <HStack spacing={1} flexShrink={0}>
        <HStack spacing={0.5} pr={2} borderRight="1px solid" borderColor={colors.border.subtle}>
          {[
            ['file', 'Создать файл', FiFileText], ['directory', 'Создать папку', FiFolder],
          ].map(([operation, label, icon]) => <Button key={operation} size="document" variant="ghost" px={2} minW="34px"
            aria-label={label} title={label}
            isDisabled={Boolean(terminal.busy || saved.busy || entry.awaitingReady || !reads.validated || editor.busy || git.busy || isolatedClone.busy || cloneDestinationPending || assistantRunning)}
            onClick={() => openCreate(operation)}>
            <Icon as={icon} boxSize={3.5} /><Text as="span" className="ide-toolbar-file-label">{label}</Text>
          </Button>)}
        </HStack>
        <Button size="document" variant="ghost" px={2} minW="34px" aria-label="Клонировать по ссылке" title="Клонировать по ссылке"
          isDisabled={Boolean(terminal.busy || saved.busy || entry.awaitingReady || !reads.validated || editor.busy || git.busy || isolatedClone.busy || recovery.loading || recovery.error || assistantRunning)} onClick={() => openClone()}>
          <Icon as={FiGitBranch} boxSize={3.5} /><Text as="span" className="ide-toolbar-clone-label">Клонировать</Text>
        </Button>
        {!git.data?.initialized && <Button size="document" variant="ghost" px={2} aria-label="Инициализировать Git" title="Инициализировать Git"
          isDisabled={Boolean(terminal.busy || saved.busy || entry.awaitingReady || !reads.validated || editor.busy || git.busy || isolatedClone.busy || cloneDestinationPending || assistantRunning)}
          onClick={() => guard(() => { void git.run('init'); })}>Git init</Button>}
        {git.data?.initialized && <Text className="ide-toolbar-branch" fontSize="11px" color={colors.fg[3]} maxW="100px" isTruncated title={`Git · ${git.data.branch || 'detached HEAD'}`}>{git.data.branch || 'detached HEAD'}</Text>}
      </HStack>}
      {!creating && repositories.selected && saved.available && <HStack spacing={1} flexShrink={0}>
        <Button size="document" variant="workbenchSecondary" px={2} minW="34px" aria-label="Сохранить проект"
          title={editor.file ? 'Сначала завершите редактирование файла' : saved.intent ? 'Проверьте предыдущий запрос в истории' : 'Сохранить проект вне временной среды'}
          isLoading={saved.busy === 'save'} isDisabled={Boolean(terminal.busy || saved.busy || saved.loading || saved.intent || editor.file || editor.busy || git.busy || isolatedClone.busy || assistantRunning || !reads.validated || reads.runtime?.state !== 'ready' || !saved.history)}
          onClick={saved.save}><Icon as={FiSave} boxSize={3.5} /></Button>
        <Button ref={historyTrigger} size="document" variant="workbenchSecondary" px={2} minW="34px" aria-label="История проекта" title="История проекта"
          onClick={openHistory}><Icon as={FiClock} boxSize={3.5} /></Button>
      </HStack>}
      {!creating && repositories.selected && <Button ref={consoleTrigger} size="document" variant="ghost" px={2} minW="34px"
        aria-label="Консоль" title="Консоль" aria-pressed={consoleOpen} bg={consoleOpen ? colors.accent.subtle : undefined}
        onClick={() => { setConsoleOpen(value => !value); setPane('code'); }}><Icon as={FiTerminal} boxSize={3.5} /></Button>}
      {repositories.status === 'ready' && repositories.items.length > 0 && <Button size="document" variant="workbenchSecondary"
        minW="34px" px={2} aria-label={creating ? 'К репозиторию' : 'Новый проект'} title={creating ? 'К репозиторию' : 'Новый проект'}
        isDisabled={Boolean(terminal.busy || saved.busy || entry.waiting || entry.error || setup.busy || editor.busy || git.busy || isolatedClone.busy || assistantRunning)} onClick={() => guard(() => { editor.discard(); setCreating((value) => !value); })}>
        <Icon as={creating ? FiFolder : FiPlus} boxSize={3.5} />
        <Text as="span" className="ide-toolbar-project-label">{creating ? 'К репозиторию' : 'Новый проект'}</Text>
      </Button>}
      <IdeStatusNotices notices={notices} activity={activity} recovery={cloneNotice ? <IdeCloneRecoveryBar
        recovery={recovery} repositoryId={repositories.selectedId}
        disabled={Boolean(terminal.busy || entry.waiting || editor.busy || git.busy || isolatedClone.busy || assistantRunning)}
        onResume={() => openClone()} onNew={() => openClone(true)}
        onOpen={() => guard(() => { editor.discard(); repositories.accept(recovery.attempt.repository); setPane('files'); })} /> : null} />
      <Button size="document" variant="workbenchSecondary" aria-label="Обновить IDE" title="Обновить IDE"
        isDisabled={!threadId || Boolean(saved.busy) || initial || entry.waiting || repositories.loading || reads.loading
          || Boolean(repositories.selectedId && !reads.validated && !reads.error)
          || Boolean(setup.busy || editor.busy || git.busy || isolatedClone.busy || assistantRunning)} onClick={refresh}>
        <Icon as={FiRefreshCw} boxSize={3.5} />
      </Button>
    </Flex>
    {initial || entry.waiting ? <Box flex="1" display="flex" alignItems="center" justifyContent="center">
      {entry.waiting && assistantRunning ? <Text role="status" p={4} fontSize="sm" color={colors.fg[3]}>Подготовка IDE начнётся после завершения текущего действия.</Text>
        : <AppLoading label={entry.waiting ? 'Подготавливаю проект и среду IDE…' : 'Загружаю IDE…'} />}
    </Box>
      : entry.error ? <Flex flex="1" minH={0} overflowY="auto" align="center" justify="center" p={6}>
        <Box maxW="440px"><Text as="h1" fontSize="lg" fontWeight="semibold">Не удалось подготовить IDE</Text>
          <Text mt={2} fontSize="sm" color={colors.fg[3]}>Результат подготовки не подтверждён. Повторная проверка использует тот же проект и не создаёт новую среду вместо существующей.</Text>
          <Button mt={3} size="document" variant="workbenchSecondary" onClick={entry.retry}>Повторить подготовку</Button>
        </Box>
      </Flex>
      : repositories.error && !repositories.items.length ? <Flex flex="1" minH={0} overflowY="auto" align="center" justify="center" p={6}>
        <Box maxW="440px"><Text as="h1" fontSize="lg" fontWeight="semibold">Не удалось загрузить IDE</Text>
          <ReadNotice onRetry={() => repositories.load(repositories.failedOffset)}>Не удалось получить список репозиториев. Проверьте соединение и повторите чтение. Сохранённые данные не изменены.</ReadNotice>
          <Text fontSize="xs" color={colors.fg[4]}>Можно переключиться в Чат или PDF. Создание проекта появится после загрузки списка.</Text>
        </Box>
      </Flex>
      : creating || !threadId || (!repositories.items.length && repositories.status === 'ready') ? <IdeProjectStart setup={setup} hasThread={Boolean(threadId)} /> : repositories.selected && <>
        <HStack display={wide ? 'none' : 'flex'} role="group" aria-label="Области IDE" px="8px" py="4px" spacing="8px" flexShrink={0} borderBottom="1px solid" borderColor={colors.border.subtle}>
          {[['files', 'Файлы'], ['code', 'Код'], ['agent', 'Агент'], ['graph', 'Graphify']].map(([value, label]) => <Button key={value} size="document" variant={pane === value ? 'workbenchPrimary' : 'ghost'}
            px="12px" aria-pressed={pane === value} onClick={() => setPane(value)}>{label}</Button>)}
        </HStack>
        <Box display={wide ? 'grid' : 'flex'} gridTemplateColumns={`${split.value}fr 6px ${100 - split.value}fr`} flex="1" minH={0} minW={0} data-testid="ide-workbench-panels">
          <Box minH={0} minW={0} display={wide ? 'grid' : ['files', 'code'].includes(pane) ? 'flex' : 'none'}
            gridTemplateColumns={`${treeSplit.value}fr 6px ${100 - treeSplit.value}fr`} flex="1">
          <Flex as="aside" aria-label="Файлы репозитория" direction="column" minW={0} minH={0}
            display={wide || pane === 'files' ? 'flex' : 'none'}
            w="100%" pb="var(--app-safe-bottom, 0px)" flexShrink={0} sx={{ containerType: 'inline-size', containerName: 'ide-file-pane' }}
            borderRightWidth={{ base: 0, md: '1px' }} borderRightStyle="solid" borderColor={colors.border.subtle}>
            <HStack px={3} h={{ base: `${documentControls.mobile}px`, md: `${documentControls.desktop}px` }} spacing={2} flexShrink={0} minW={0}><Icon as={FiFolder} boxSize={3.5} flexShrink={0} color={colors.fg[3]} /><Text as="h2" fontSize="xs" minW={0} flex="1" isTruncated title="Репозиторий">Репозиторий</Text>
              {(treeSelection || reads.file) && <IdeMoveFileButton isDisabled={moveBlocked} onClick={() => openMove(treeSelection || reads.file)} />}
            </HStack>
            {reads.runtime?.state === 'expired' && <IdeProjectRecovery saved={saved} onOpenHistory={openHistory} />}
            {reads.tree ? <Box flex="1" minH={0}>
              <WorkspaceTree key={repositories.selectedId} entries={reads.tree.entries} selected={reads.file?.path}
                label="Дерево репозитория" onSelect={selectFile} onInspect={setTreeSelection} onMove={moveInTree}
                moveDisabled={moveBlocked}
                disabled={reads.loading || reads.fileLoading || Boolean(editor.busy || saved.busy)} />
            </Box> : reads.runtime?.state !== 'expired' && <Text p={3} fontSize="xs" color={colors.fg[4]}>{reads.loading ? 'Загружаю дерево…' : 'Дерево ещё не загружено.'}</Text>}
            {reads.tree?.truncated && <Text p={3} fontSize="xs" color={colors.warning}>Дерево показано не полностью: достигнут лимит просмотра.</Text>}
            {treeMoveFeedback && editor.busy === 'move' && <Text role="status" px={3} py={2} fontSize="xs" color={colors.fg[3]}>Перемещаю…</Text>}
            {treeMoveFeedback && editor.error && <Text role="alert" px={3} py={2} fontSize="xs" color={colors.warning}>{editor.error}</Text>}
            {treeMoveFeedback && editor.outcome && <Text role="status" px={3} py={2} fontSize="xs" color={colors.fg[3]}>{editor.outcome}</Text>}
          </Flex>
          {wide && <Box {...treeSplit.props} {...separatorStyle} />}
          <Box flex="1" minH={0} minW={0} display={wide || pane === 'code' ? 'grid' : 'none'}
            gridTemplateRows={consoleOpen ? `minmax(64px, ${consoleSplit.value}fr) 6px minmax(110px, ${100 - consoleSplit.value}fr)` : 'minmax(0, 1fr)'}>
            <Box minH={0} minW={0} overflow="hidden"><IdeCodePane reads={guardedReads} focusRef={codeRef} editor={{ ...editor, busy: editor.busy || saved.busy || (terminal.busy === 'agent' ? '' : terminal.busy), writeBlocked: terminal.busy === 'agent', canMove: !moveBlocked, ...(treeMoveFeedback ? { error: '', outcome: '' } : {}) }} onBrowse={() => setPane('files')} onMove={() => openMove()} singlePane={!wide} safeBottom={!consoleOpen} /></Box>
            {consoleOpen && <><Box {...consoleSplit.props} h="6px" cursor="row-resize" sx={{ touchAction: 'none' }} bg={colors.border.subtle}
              _hover={{ bg: colors.blue[500] }} _focusVisible={{ outline: `2px solid ${colors.border.focus}`, outlineOffset: '-2px' }} />
              <IdeConsole console={terminal} dirty={editor.dirty} unavailable={!reads.validated || reads.runtime?.state !== 'ready'}
                blocked={Boolean(editor.busy || saved.busy || git.busy || isolatedClone.busy || assistantRunning || entry.awaitingReady || cloneDestinationPending)}
                onCollapse={() => { setConsoleOpen(false); consoleTrigger.current?.focus(); }} /></>}
          </Box>
          </Box>
          {wide && <Box {...split.props} {...separatorStyle} />}
          <Box w="100%" flexShrink={0} minH={0} minW={0}
            display={wide || pane === 'agent' ? 'block' : 'none'} borderLeftWidth={wide ? '1px' : 0} borderColor={colors.border.subtle}>
            <IdeAgentPane assistantRef={assistantRef} name={repositories.selected.name} statusHint={!agentBlocked ? ''
              : terminal.busy ? 'Дождитесь результата команды консоли.' : editor.file ? 'Завершите редактирование файла перед отправкой.' : git.busy ? 'Дождитесь завершения операции Git.'
                : reads.loading ? 'Проверяю выбранную среду…' : reads.error ? 'Не удалось проверить среду. Обновите IDE.'
                  : reads.runtime?.state === 'expired' ? 'Среда завершена. Загруженные исходники доступны для просмотра.'
                    : ['unknown', 'unavailable', 'pending', 'dispatching'].includes(reads.runtime?.state) ? 'Готовность среды не подтверждена. Обновите IDE.'
                      : 'Запустите среду перед отправкой.'} />
          </Box>
          {!wide && pane === 'graph' && <Box p={4} flex="1" minW={0} overflowY="auto" pb="calc(16px + var(--app-safe-bottom, 0px))">
            <Text as="h2" fontSize="sm" fontWeight={600}>Graphify</Text>
            <Text mt={2} fontSize="xs" color={colors.fg[3]}>Граф этого репозитория ещё не подключён к IDE. Анализ и запуск агента при открытии вкладки не выполняются.</Text>
            <Button mt={3} size="document" variant="workbenchSecondary" onClick={() => setPane('files')}>Открыть файлы</Button>
          </Box>}
        </Box>
      </>}
    {repositories.nextOffset !== null && <Box p={2} borderTop="1px solid" borderColor={colors.border.subtle}>
      <Button size="document" variant="workbenchSecondary" isDisabled={repositories.loading} onClick={() => repositories.load(repositories.nextOffset)}>Ещё репозитории</Button>
    </Box>}
    {active && dialogOwner === dialogContext && fileDialog && <IdeCreateFileDialog key={`${repositories.selectedId}:${fileDialog}`} operation={fileDialog} editor={editor} onClose={() => setFileDialog('')} />}
    {active && dialogOwner === dialogContext && cloneOpen && <IdeCloneDialog key={repositories.selectedId} git={git} isolated={cloneView} onClose={() => setCloneOpen(false)} />}
    {active && dialogOwner === dialogContext && moveFile && reads.tree && <IdeMoveFileDialog key={`${repositories.selectedId}:${moveFile.path}`} file={moveFile} tree={reads.tree} editor={editor} onClose={() => setMoveFile(null)} />}
    {saved.open && <IdeProjectHistory key={dialogContext} saved={saved} name={repositories.selected?.name}
      blocked={Boolean(editor.file || editor.busy || git.busy || isolatedClone.busy || assistantRunning)} onRestore={guard}
      onClose={closeHistory} finalFocusRef={historyReturnFocus} />}
  </Flex>;
}
