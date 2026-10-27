import { useEffect, useRef, useState } from 'react';
import {
  Box, Button, Drawer, DrawerBody, DrawerCloseButton, DrawerContent, DrawerHeader,
  DrawerOverlay, Flex, Grid, HStack, Text, useMediaQuery,
} from '@chakra-ui/react';
import { borderRadius, colors } from '@theme/tokens';
import { DRAWER_CLOSE_BUTTON_PROPS } from '@theme/drawer';
import { usePdfSplit } from '../model/usePdfSplit';
import { DocumentForgePanel } from './DocumentForgePanel';
import { PdfMaterialsPanel } from './PdfMaterialsPanel';
import { PdfDocumentEditor } from './PdfDocumentEditor';
import { PdfProposalReview } from './PdfProposalReview';
import { DocumentChecksBar } from './DocumentChecksBar';
import { PdfStudioToolbar } from './PdfStudioToolbar';
import { PdfBuildActivity, PDF_BUILD_RUNNING, canPreviewBuild } from './PdfBuildActivity';
import { PdfStudioReadState } from './PdfStudioReadState';
import { PdfNewDocumentDialog } from './PdfNewDocumentDialog';

const PANES = ['Редактор', 'Превью'];

export function PdfStudio({ work, active, assistantRef, onOpenFile, onContextChange, onDirtyChange, onRegister, proposalId, assistantRunning, assistantExpanded = false }) {
  const doc = work.document;
  const [wide] = useMediaQuery('(min-width: 1100px)');
  const [pane, setPane] = useState('Редактор');
  const [drawer, setDrawer] = useState('');
  const [newDocument, setNewDocument] = useState(false);
  const [checks, setChecks] = useState(false);
  const [materialError, setMaterialError] = useState('');
  const [sourceRequest, setSourceRequest] = useState(null);
  const [focusSource, setFocusSource] = useState(false);
  const sourceEditorRef = useRef(null);
  const panelTriggerRef = useRef(null);
  const newDocumentTriggerRef = useRef(null);
  const scope = useRef(null);
  const sourceTicket = useRef(0);
  useEffect(() => { if (!active) setDrawer(''); }, [active]);
  useEffect(() => { setNewDocument(false); }, [work.threadId, active]);
  const horizontal = usePdfSplit('x', 50);
  const [selectedBlocks, setSelectedBlocks] = useState([]);
  const [editorDirty, setEditorDirty] = useState(false);
  const updateDirty = (value) => { setEditorDirty(value); onDirtyChange?.(value); };
  const project = doc.project;
  const scopeKey = `${work.threadId}/${project?.path}/${active}`;
  if (scope.current?.key !== scopeKey) scope.current = { key: scopeKey };
  const openSource = (path) => {
    if (!project?.path || !active) return false;
    const owner = scope.current;
    const ticket = ++sourceTicket.current;
    const current = () => scope.current === owner && sourceTicket.current === ticket;
    setMaterialError('');
    return onOpenFile(path, {
      onOpened: () => {
        if (!current()) return;
        doc.selectProject(project.path);
        setSourceRequest({ path, project: project.path });
        setFocusSource(true);
        setPane('Редактор'); setDrawer('');
      },
      onFailed: () => {
        if (current()) setMaterialError('Не удалось открыть исходник. Обновите список и попробуйте ещё раз.');
      },
    });
  };
  const running = PDF_BUILD_RUNNING.has(doc.build?.state);
  const projects = (work.hub.workspace.entries || [])
    .filter((item) => /(^|\/)document\.toml$/i.test(item.path || ''))
    .map((item) => ({ value: item.path.replace(/\/?document\.toml$/i, ''),
      label: project?.path === item.path.replace(/\/?document\.toml$/i, '')
        ? doc.authoring?.value?.draft?.title || project.title || project.profile?.label || 'PDF-проект'
        : item.path.replace(/\/?document\.toml$/i, '').split('/').pop() }));
  const context = project && work.hub.workspace.state === 'ready' && doc.projectState !== 'unavailable' ? {
    project_id: project.project_id,
    path: project.path, expected_revision: project.revision,
    authoring_version: project.authoring_version || 0,
    draft_digest: project.draft_digest || null, block_ids: selectedBlocks,
  } : null;
  const contextKey = JSON.stringify(context);
  useEffect(() => { if (active) onContextChange?.(context); }, [active, contextKey, onContextChange]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setSelectedBlocks([]); }, [project?.path]);
  const workspacePending = work.hub.loading && work.hub.workspace.state !== 'ready';
  const projectPending = !project && doc.projectState === 'loading';
  const projectFailed = doc.projectState === 'unavailable';
  const preparation = work.pdfPreparation;
  const retainedProject = Boolean(project && ['ready', 'unavailable', 'expired'].includes(work.hub.workspace.state));
  const blocked = Boolean(work.dirty || editorDirty || doc.busy || running
    || ['preparing', 'unavailable', 'expired'].includes(preparation?.status)
    || work.hub.workspace.state !== 'ready' || projectPending || projectFailed);
  const freshWorkspace = preparation?.status === 'expired' || work.hub.workspace.state === 'expired'
    || work.hub.workspace.state === 'absent';
  const newDocumentBlocked = Boolean(work.dirty || editorDirty || work.busy || doc.busy || running || assistantRunning
    || preparation?.status === 'preparing' || workspacePending || projectPending
    || (!freshWorkspace && work.hub.workspace.state !== 'ready'));
  const previewVisible = active && (wide || pane === 'Превью');
  const pdf = doc.build?.artifacts?.some((item) => item.role === 'pdf');
  const buildStatus = <PdfBuildActivity document={doc} initialLabel={projectPending ? 'Загружаю сведения о PDF…' : 'Ещё не собирался'} />;
  const openPdf = () => {
    setPane('Превью');
    if (canPreviewBuild(doc.build)) doc.openPreview();
  };
  const separator = {
    flexShrink: 0, bg: colors.border.subtle, sx: { touchAction: 'none' },
    _hover: { bg: colors.blue[500] },
    _focusVisible: { outline: `2px solid ${colors.border.focus}`, outlineOffset: '-2px' },
  };
  return <Flex data-testid="pdf-studio" direction="column" flex="1" w="full" h="full" minH={0} minW={0} overflow="hidden" bg={colors.ink[950]}>
    <PdfStudioToolbar document={doc} projects={projects} dirty={work.dirty || editorDirty}
      assistantRunning={assistantRunning} running={running} blocked={blocked}
      newDocumentBlocked={newDocumentBlocked}
      onOpenPdf={openPdf}
      onNewDocument={(event) => { newDocumentTriggerRef.current = event.currentTarget; setNewDocument(true); }}
      onPanel={(label, trigger) => { panelTriggerRef.current = trigger; setFocusSource(false); setDrawer(label); }} />
    {!retainedProject && preparation?.status === 'preparing' ? <PdfStudioReadState loading label="Готовлю первый PDF-проект…" />
      : !retainedProject && preparation?.status === 'unavailable' ? <PdfStudioReadState label="Подготовка PDF-проекта пока не подтверждена. Существующие файлы не изменены." retryLabel="Повторить подготовку" onRetry={preparation.retry} />
      : !retainedProject && (preparation?.status === 'expired' || work.hub.workspace.state === 'expired')
        ? <PdfStudioReadState label="Среда PDF завершена. Чтобы продолжить, выберите «Новый документ» вверху. Старый документ не будет восстановлен." />
      : !retainedProject && workspacePending ? <PdfStudioReadState loading label="Загружаю PDF-студию…" />
      : !retainedProject && !['ready', 'absent', 'expired'].includes(work.hub.workspace.state)
        ? <PdfStudioReadState label="Не удалось загрузить рабочее место PDF. Данные не изменены." onRetry={() => work.load()} />
      : !retainedProject && work.hub.workspace.state !== 'ready' ? <Flex direction="column" align="center" justify="center" flex="1" p={6} gap={3}>
      <Text fontSize="lg">PDF-студия</Text>
      <Text color={colors.fg[3]} textAlign="center">Документы, статьи и PDF-презентации — с редактором, ассистентом и большим превью.</Text>
      <Button size="document" variant="workbenchPrimary" onClick={work.activateWorkspace} isLoading={work.busy === 'activate'}>Создать рабочее место для PDF</Button>
    </Flex> : <>
      {!wide && <HStack px={3} py={1} spacing={1} flexShrink={0} flexWrap="wrap" role="group" aria-label="Области PDF-студии">
        {PANES.map((name) => <Button key={name} size="document" aria-pressed={pane === name}
          variant="ghost" bg={pane === name ? colors.surface.tint3 : undefined} onClick={() => setPane(name)}>{name}</Button>)}
        <Box ml="auto" minW={0}>{buildStatus}</Box>
      </HStack>}
      <Grid flex="1" minH={0} minW={0} overflow="hidden"
        // Состояние передаёт владелец ассистента: геометрия не зависит от
        // селекторов тестов или наличия дочерних элементов в портале.
        templateRows={!wide && !assistantExpanded ? 'minmax(44px, 1fr) minmax(0, auto)' : 'minmax(0, 1fr) auto'}
        templateColumns={wide ? `${horizontal.value}% 6px minmax(0, 1fr)` : 'minmax(0, 1fr)'}>
          <Box gridColumn={1} gridRow={1} minH={0} minW={0} overflow="hidden"
            display={wide || pane === 'Редактор' ? 'flex' : 'none'} flexDirection="column">
            {projectPending || (projectFailed && !project)
              ? <PdfStudioReadState loading={projectPending} label={projectPending ? 'Загружаю PDF-проект…' : 'Не удалось загрузить PDF-проект. Исходники не изменены.'}
                  onRetry={() => doc.loadProject()} />
              : project ? <PdfDocumentEditor key={`${work.threadId}/${project.path}`} work={work} active={active} onOpenFile={openSource}
              editorRef={sourceEditorRef}
              sourceRequest={sourceRequest?.project === project.path && sourceRequest.path === work.file.path ? sourceRequest : null}
              selectedBlocks={selectedBlocks} onSelectBlocks={setSelectedBlocks} onDirtyChange={updateDirty} onRegister={onRegister} />
              : <Box p={5} h="full" overflowY="auto"><DocumentForgePanel document={doc} section="create" previewVisible={false} /></Box>}
          </Box>
          <Flex data-testid="pdf-assistant-dock" gridColumn={1} gridRow={2} direction="column"
            minH={0} minW={0} maxH="min(420px, calc(var(--app-visual-height, 100dvh) / 2))" overflow="hidden"
            borderTop="1px solid" borderColor={colors.border.subtle}>
            {(selectedBlocks.length > 0 || proposalId) && <HStack px={4} py={2} flexWrap="wrap" flexShrink={0}>
              {selectedBlocks.length > 0 && <Button size="sm" variant="ghost" onClick={() => setSelectedBlocks([])}>
                {`Выбрано блоков: ${selectedBlocks.length} · Снять выделение`}</Button>}
              <PdfProposalReview threadId={work.threadId} proposalId={proposalId} project={project}
                work={work} dirty={work.dirty || editorDirty} active={active} />
            </HStack>}
            <Flex ref={assistantRef} direction="column" flex="1" minH={0} minW={0} overflow="hidden" />
          </Flex>
        {wide && <Box {...separator} {...horizontal.props} gridColumn={2} gridRow="1 / 3" w="6px" cursor="col-resize" />}
        <Flex data-testid="pdf-preview-pane" direction="column" gridColumn={wide ? 3 : 1} gridRow={wide ? '1 / 3' : 1}
          minH={0} minW={0} overflowY="auto" display={wide || pane === 'Превью' ? 'flex' : 'none'}>
          <HStack data-testid="pdf-preview-header" p={3} flexShrink={0} justify="space-between" align="start" minW={0} gap={2}>
            <Text fontWeight={600} fontSize="13px" flexShrink={0}>Предпросмотр PDF</Text>
            {wide && <Box minW={0}>{buildStatus}</Box>}
          </HStack>
          {(doc.previewUrl || pdf) && (work.dirty || editorDirty || running || (doc.build?.source_digest && project?.source_digest !== doc.build.source_digest))
            && <Text role="status" px={3} pb={2} fontSize="12px" color={colors.warning}>
              {running ? 'Превью предыдущей сборки. Новая сборка ещё выполняется.' : 'Превью предыдущей сборки. Есть несобранные правки.'}
            </Text>}
          <Box flex="1" minH={wide ? 0 : '120px'} px={3} pb={3}>
            {previewVisible && doc.previewUrl ? <Box as="iframe" title="Предпросмотр PDF" src={doc.previewUrl}
              w="full" h="full" border="1px solid" borderColor={colors.border.subtle} borderRadius={borderRadius.md} />
              : <Flex direction="column" h="full" align="center" justify="center" p={5} gap={3}>
                <Text color={colors.fg[3]} textAlign="center">{projectPending ? 'Загружаю сведения о PDF…'
                  : pdf ? 'Последняя сборка доступна для просмотра.' : 'Соберите черновик, чтобы увидеть PDF.'}</Text>
                {!projectPending && !wide && <Button size="document" variant="workbenchSecondary" onClick={() => setPane('Редактор')}>К редактору</Button>}
              </Flex>}
          </Box>
          {!projectPending && <DocumentChecksBar document={doc} expanded={checks} onToggle={() => setChecks(!checks)} scrollWithinPreview={!wide} />}
        </Flex>
      </Grid>
    </>}
    {newDocument && active && <PdfNewDocumentDialog key={work.threadId}
      finalFocusRef={newDocumentTriggerRef}
      document={{ ...doc, createProject: (selection) => doc.createProject(selection, { prepareWorkspace: work.activateWorkspace }) }}
      newWorkspace={freshWorkspace}
      blocked={Boolean(work.dirty || editorDirty || running || assistantRunning)}
      onClose={() => setNewDocument(false)} />}
    <Drawer isOpen={Boolean(drawer)} onClose={() => setDrawer('')} placement="right" size="md"
      finalFocusRef={focusSource ? sourceEditorRef : panelTriggerRef}>
      <DrawerOverlay /><DrawerContent bg={colors.ink[900]}><DrawerCloseButton {...DRAWER_CLOSE_BUTTON_PROPS} aria-label="Закрыть панель документа" />
        <DrawerHeader>{drawer}</DrawerHeader><DrawerBody minH={0} overflowY={drawer === 'Материалы' ? 'hidden' : 'auto'}>
          {drawer === 'Оформление' ? <DocumentForgePanel document={doc} section="formatting" previewVisible={false} blocked={blocked || assistantRunning} />
            : <PdfMaterialsPanel work={work} onOpenFile={openSource}
              blocked={blocked || assistantRunning} error={materialError} />}
        </DrawerBody></DrawerContent>
    </Drawer>
  </Flex>;
}
