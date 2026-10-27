import { useEffect, useMemo, useRef, useState } from 'react';
import { Box, Button, Checkbox, HStack, Icon, IconButton, Text, VStack, useDisclosure } from '@chakra-ui/react';
import { FiCheck, FiLayers, FiRotateCcw } from '@shared/icons';
import AppTextarea from '@shared/controls/AppTextarea';
import AppSelect from '@shared/controls/AppSelect';
import AppLoading from '@shared/controls/AppLoading';
import { colors, spacing } from '@theme/tokens';
import { saveDocumentDraft } from '@api/chat';
import { getWorkspaceActorSession } from '../model/workspaceSession';
import { WorkFileEditor } from './WorkFileEditor';
import { PdfBlockFields } from './PdfBlockFields';
import { PdfDocumentOutline } from './PdfDocumentOutline';
import { PdfStartContentDialog } from './PdfStartContentDialog';
import { projectImageOptions } from '../model/documentAssets';
import './PdfDocumentEditor.css';
import { useDocumentSources } from '../model/useDocumentSources';
import { PdfCitationSource } from './PdfCitationSource';
import { PdfDraftRecovery } from './PdfDraftRecovery';
import { initialDocumentDraft } from '../model/initialDocumentDraft';

const LABELS = { section: 'Заголовок', paragraph: 'Абзац', list: 'Список', table: 'Таблица',
  figure: 'Изображение', equation: 'Формула', callout: 'Выноска', slide: 'Слайд', signature: 'Подписи', citation: 'Цитирование' };

export function PdfDocumentEditor({ work, active, onOpenFile, sourceRequest, editorRef, selectedBlocks, onSelectBlocks, onDirtyChange, onRegister }) {
  const source = work.document.authoring;
  const project = work.document.project;
  const canWrite = work.hub?.workspace?.state === 'ready'
    && !['loading', 'refreshing', 'unavailable'].includes(work.document.projectState);
  const images = useMemo(() => projectImageOptions(work.hub?.workspace?.entries, project?.path, work.hub?.library?.items),
    [work.hub?.workspace?.entries, work.hub?.library?.items, project?.path]);
  const [mode, setMode] = useState('content');
  const [draft, setDraft] = useState(null);
  const [base, setBase] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [newKind, setNewKind] = useState('paragraph');
  const [citationSource, setCitationSource] = useState('');
  const sources = useDocumentSources({ threadId: work.threadId, project,
    refreshProject: work.document.loadProject,
    enabled: active && (newKind === 'citation' || Boolean(draft?.blocks.some((block) => block.kind === 'citation'))) });
  const startContent = useDisclosure();
  const startContentTrigger = useRef(null);
  const closeStartContent = startContent.onClose;
  const newBlockOrdinal = useRef(0);
  const generation = useRef(0);
  const inFlight = useRef(false);
  const current = useRef(null);
  const baseFacts = useRef(null);
  const blockRefs = useRef(new Map());
  const pendingBlockFocus = useRef(null);
  useEffect(() => {
    const id = pendingBlockFocus.current;
    if (!id) return;
    pendingBlockFocus.current = null;
    if (!active || mode !== 'content') return;
    const node = blockRefs.current.get(id);
    node?.scrollIntoView({ block: 'nearest', behavior: 'instant' });
    (node?.querySelector('textarea') || node?.querySelector('input:not([type="checkbox"])'))?.focus({ preventScroll: true });
  }, [active, draft?.blocks, mode]);
  const outline = useDisclosure();
  const closeOutline = outline.onClose;
  const outlineTrigger = useRef(null);
  const outlineFocus = useRef(null);
  useEffect(() => { if (!active) { closeOutline(); closeStartContent(); } }, [active, closeOutline, closeStartContent]);
  current.current = { active, path: project?.path, canWrite, sourceReady: source?.state === 'ready' };
  const dirty = Boolean(draft && JSON.stringify(draft) !== base);
  useEffect(() => { onDirtyChange?.(dirty); }, [dirty, onDirtyChange]);
  useEffect(() => { onRegister?.({ abandon: () => { setDraft(base ? JSON.parse(base) : null); return true; } }); }, [base, onRegister]);
  useEffect(() => {
    generation.current += 1;
    setDraft(null); setBase(''); setError(''); setSaving(false); setMode('content');
    setCitationSource('');
    return () => { generation.current += 1; };
  }, [project?.path]);
  useEffect(() => { if (sourceRequest) setMode('latex'); }, [sourceRequest]);
  useEffect(() => {
    if (active && mode === 'latex' && sourceRequest) editorRef?.current?.focus();
  }, [active, editorRef, mode, sourceRequest]);
  const openSource = () => onOpenFile(sourceRequest?.path
    || (work.file.path?.startsWith(`${project.path}/`) ? work.file.path : `${project.path}/main.tex`));
  useEffect(() => {
    if (!source?.value?.draft || dirty) return;
    setDraft(source.value.draft);
    setBase(JSON.stringify(source.value.draft));
    baseFacts.current = { expected_revision: project.revision,
      authoring_version: source.value.authoring_version ?? project.authoring_version,
      draft_digest: source.value.draft_digest ?? project.draft_digest };
  }, [source?.value?.draft]); // eslint-disable-line react-hooks/exhaustive-deps
  const save = async (initial = false) => {
    if (!active || !canWrite || (!initial && source?.state !== 'ready')
      || (!dirty && !initial) || saving || inFlight.current || !project?.path || work.dirty) return;
    inFlight.current = true;
    const ticket = generation.current;
    const path = project.path;
    const submitted = JSON.stringify(initial ? initialDocumentDraft(project.kind === 'presentation') : draft);
    let lease;
    setSaving(true); setError('');
    try {
      const api = await import('@api/chat');
      const actorSession = getWorkspaceActorSession();
      lease = await api.acquireWorkspaceLease(work.threadId, path, { actorSession });
      if (ticket !== generation.current || !current.current.active || !current.current.canWrite
        || (!initial && !current.current.sourceReady) || current.current.path !== path) return;
      const result = await saveDocumentDraft(work.threadId, {
        path, draft: JSON.parse(submitted), ...(initial ? {
          expected_revision: project.revision, authoring_version: 0, draft_digest: null,
        } : baseFacts.current),
        fence: Number(lease.fence),
      }, { actorSession });
      if (ticket !== generation.current) return;
      baseFacts.current = { expected_revision: result.revision,
        authoring_version: result.authoring_version, draft_digest: result.draft_digest };
      if (!initial) setBase(submitted);
      await work.document.loadProject(path);
      await work.document.loadAuthoring(path);
      await work.load({ background: true });
      return result;
    } catch (failure) {
      if (ticket === generation.current) setError(Number(failure?.status || failure?.response?.status) === 409
        ? 'Версия документа изменилась. Ваш текст сохранён в редакторе; автоматической перезаписи нет.'
        : 'Сохранить изменения не удалось. Черновик остался в редакторе.');
    } finally {
      if (lease?.fence) {
        const { releaseWorkspaceLease } = await import('@api/chat');
        await releaseWorkspaceLease(work.threadId, path, Number(lease.fence), { actorSession: getWorkspaceActorSession() }).catch(() => {});
      }
      inFlight.current = false;
      if (ticket === generation.current) setSaving(false);
    }
  };
  const semantic = mode === 'content' && draft;
  const saveLabel = saving ? 'Сохраняю…' : dirty ? 'Сохранить' : 'Сохранено';
  const effectiveKind = project.kind === 'presentation' ? 'slide' : newKind;
  return <FlexEditor onKeyDown={(event) => {
    if (mode === 'content' && (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
      event.preventDefault();
      if (dirty && !saving) void save();
    }
  }}>
    <PdfDraftRecovery work={work} draft={draft} mode={mode} />
    <HStack className="pdf-editor-toolbar" data-testid="pdf-editor-toolbar" px={2} py={{ base: 1, md: 2 }} spacing={1} flexShrink={0} flexWrap="wrap" borderBottom="1px solid" borderColor={colors.border.subtle}>
      <Button size="document" variant="ghost" aria-pressed={mode === 'content'} bg={mode === 'content' ? colors.surface.tint3 : undefined} isDisabled={work.dirty}
        onClick={() => setMode('content')}>Содержание</Button>
      <Button size="document" variant="ghost" aria-pressed={mode === 'latex'} bg={mode === 'latex' ? colors.surface.tint3 : undefined} isDisabled={dirty || saving}
        onClick={openSource}>LaTeX</Button>
      <Box flex="1" />
      {semantic && <Button ref={outlineTrigger} size="document" variant="ghost" data-pdf-editor-action
        aria-label="Структура" title="Структура" onClick={() => { outlineFocus.current = outlineTrigger.current; outline.onOpen(); }}>
        <Icon as={FiLayers} /><Text as="span" data-action-label ml={2}>Структура</Text>
      </Button>}
      {semantic ? <Button size="document" data-pdf-editor-action data-pdf-save-action aria-label={saveLabel}
        title={dirty ? 'Сохранить · Ctrl+S' : saveLabel} aria-busy={saving}
        onClick={() => save()} isLoading={saving} loadingText={saveLabel} variant={dirty ? 'workbenchPrimary' : 'workbenchSecondary'} isDisabled={!dirty || work.dirty || !canWrite || source?.state !== 'ready'}>
        <Icon as={FiCheck} /><Text as="span" data-action-label ml={2}>{saveLabel}</Text>
      </Button> : <Text data-pdf-editor-status fontSize="11px" color={colors.fg[3]} role="status">
        {source?.state === 'loading' ? 'Загружаю структуру…' : 'Исходники LaTeX'}
      </Text>}
      {dirty && <IconButton size="document" px={0} variant="ghost" aria-label="Отменить правки" title="Отменить правки"
        icon={<FiRotateCcw />} isDisabled={saving} onClick={() => { setDraft(JSON.parse(base)); setError(''); }} />}
    </HStack>
    {error && <Text role="alert" p={3} color={colors.warning}>{error}</Text>}
    {semantic ? <>
      <HStack data-testid="pdf-block-toolbar" flexShrink={0} px={3} py={{ base: 1, md: 2 }} spacing={2} borderBottom="1px solid" borderColor={colors.border.subtle}>
        <Box data-testid="pdf-block-type-selector" flex="1" minW={0} maxW="200px"><AppSelect ariaLabel="Тип нового блока" value={effectiveKind} onChange={setNewKind} size="document"
          options={Object.entries(LABELS).filter(([kind]) => project.kind === 'presentation' ? kind === 'slide' : kind !== 'slide')
            .map(([value, label]) => ({ value, label }))} /></Box>
        <Button size="document" flexShrink={0} variant="workbenchSecondary" isDisabled={saving || draft.blocks.length >= 120
          || (effectiveKind === 'citation' && (sources.status !== 'ready' || !sources.sources.some((item) => item.value === citationSource)))} onClick={() => {
          const block_id = `new_${++newBlockOrdinal.current}`;
          pendingBlockFocus.current = block_id;
          const kind = effectiveKind;
          setDraft((old) => {
            const blocks = [...old.blocks];
            const lastSelected = blocks.reduce((index, block, position) => selectedBlocks.includes(block.block_id) ? position : index, -1);
            blocks.splice(lastSelected < 0 ? blocks.length : lastSelected + 1, 0, {
            block_id, kind, title: '', text: '', items: kind === 'list' ? [''] : [],
            columns: kind === 'table' ? ['Столбец 1', 'Столбец 2'] : [],
            rows: kind === 'table' ? [['', '']] : [], source_id: kind === 'citation' ? Number(citationSource) : null, asset_path: '', level: 1,
            });
            return { ...old, blocks };
          });
        }}>Добавить блок</Button>
      </HStack>
      <Box flex="1" minH={0} overflowY="auto" px={{ base: spacing.md, md: spacing.lg }} py={5}>
      {effectiveKind === 'citation' && <Box mb={4}>
        <PdfCitationSource inventory={sources} value={citationSource} onChange={setCitationSource} disabled={saving} />
      </Box>}
      <AppTextarea autoGrow variant="unstyled" aria-label="Название документа" value={draft.title} mb={5}
        fontSize={{ base: '22px', md: '26px' }} fontWeight={650} lineHeight={1.35} minH="32px"
        _focusVisible={{ boxShadow: `0 1px 0 ${colors.border.focus}` }}
        onChange={(event) => setDraft({ ...draft, title: event.target.value })} />
      <VStack spacing={4} align="stretch">{draft.blocks.map((block) => <Box key={block.block_id} role="group" minW={0}
        ref={(node) => { if (node) blockRefs.current.set(block.block_id, node); else blockRefs.current.delete(block.block_id); }}
        px={3} mx={-3} py={2} borderRadius="control" bg={selectedBlocks.includes(block.block_id) ? colors.accent.subtle : 'transparent'}
        boxShadow={selectedBlocks.includes(block.block_id) ? `inset 2px 0 0 ${colors.blue[500]}` : 'none'}>
        <Checkbox mb={1} size="sm" minH="24px" aria-label={`Выбрать блок ${block.title || LABELS[block.kind] || block.block_id}`} isChecked={selectedBlocks.includes(block.block_id)} onChange={(event) => onSelectBlocks(event.target.checked
          ? [...selectedBlocks, block.block_id] : selectedBlocks.filter((id) => id !== block.block_id))}>
          <Text fontSize="10px" color={colors.fg[4]}>{LABELS[block.kind] || 'Блок'}</Text>
        </Checkbox>
        <PdfBlockFields block={block} images={images} sources={sources} onChange={(next) => setDraft((old) => ({ ...old,
          blocks: old.blocks.map((item) => item.block_id === block.block_id ? next : item) }))} />
      </Box>)}</VStack>
      </Box>
      <PdfDocumentOutline isOpen={outline.isOpen} onClose={outline.onClose} blocks={draft.blocks} labels={LABELS}
        finalFocusRef={outlineFocus}
        onNavigate={(id) => {
          const node = blockRefs.current.get(id);
          node?.scrollIntoView({ block: 'nearest' });
          outlineFocus.current = node?.querySelector('textarea, input:not([type="checkbox"])') || outlineTrigger.current;
        }} />
    </> : mode === 'content' ? <Box p={5} overflowY="auto">
      {['loading', 'idle'].includes(source?.state) && project.authoring_version > 0
        ? <AppLoading label="Загружаю содержание документа…" />
        : <Text color={colors.fg[3]}>{source?.state === 'unavailable'
          ? 'Не удалось загрузить содержание. Исходники и готовый PDF сохранены.'
          : 'У этого LaTeX-проекта пока нет структуры для визуального редактора. Сборка PDF не преобразует исходники в блоки; текст доступен в LaTeX.'}</Text>}
      <HStack mt={3} spacing={2} flexWrap="wrap">
        {!project.authoring_version && source?.state === 'absent' && <Button ref={startContentTrigger} size="document" variant="workbenchSecondary" aria-label="Новое содержание без ИИ" isLoading={saving} isDisabled={!canWrite} onClick={startContent.onOpen}>Новое содержание</Button>}
        {source?.state === 'unavailable' && <Button size="document" variant="workbenchSecondary" onClick={() => work.document.loadAuthoring()}>Повторить загрузку</Button>}
        <Button size="document" variant="workbenchSecondary" onClick={openSource}>Открыть исходник</Button>
      </HStack>
    </Box> : sourceRequest || work.file.path?.startsWith(`${project.path}/`) ? <Box flex="1" minH={0} overflow="hidden">
      <WorkFileEditor work={work} editorRef={editorRef} /></Box>
      : <Box p={5}><Text color={colors.fg[3]}>Выберите исходник текущего проекта в «Материалах» или откройте основной файл.</Text>
        <Button mt={3} size="document" variant="workbenchSecondary" onClick={openSource}>Открыть исходник</Button></Box>}
    <PdfStartContentDialog isOpen={startContent.isOpen} onClose={startContent.onClose}
      finalFocusRef={startContentTrigger}
      onConfirm={() => { startContent.onClose(); void save(true); }} />
  </FlexEditor>;
}

function FlexEditor({ children, ...props }) {
  return <VStack {...props} align="stretch" spacing={0} h="full" minH={0} overflow="hidden"
    sx={{ containerType: 'inline-size', containerName: 'pdf-editor' }}>{children}</VStack>;
}
