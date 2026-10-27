import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Box,
  Flex,
  Tab,
  TabList,
  TabPanel,
  TabPanels,
  Tabs,
  VStack,
} from '@chakra-ui/react';
import { colors } from '@theme/tokens';
import { WORK_HUB_THEME } from '../model/theme';
import { useWorkHub } from '../model/useWorkHub';
import { useWorkbenchLayout } from '../model/useWorkbenchLayout';
import { useWorkUploadSelection } from '../model/useWorkUploadSelection';
import { useWorkContextSelection } from '../model/useWorkContextSelection';
import { WorkbenchLibraryDrawer } from './WorkbenchLibraryDrawer';
import { WorkContextDrawer } from './WorkContextDrawer';
import { WorkContextPanel } from './WorkContextPanel';
import { WorkFileUpload } from './WorkFileUpload';
import { WorkLanding } from './WorkLanding';
import { WorkSourceRail } from './WorkSourceRail';
import { WorkStatusRail } from './WorkStatusRail';
import { WorkFileEditor } from './WorkFileEditor';
import { WorkspaceTree } from './WorkspaceTree';
import { PdfStudio } from './PdfStudio';

const SECTIONS = ['workspace', 'context'];
const LIBRARY_UPLOAD_OPTIONS = { libraryOnly: true };

export default function WorkHub({
  threadId,
  invalidationVersion,
  notify,
  onCancelRun,
  onDirtyChange,
  onRequestNavigation,
  onThreadUnavailable,
  onRegisterDraftLifecycle,
  active = true,
  surface = 'work',
  assistantRef,
  onDocumentContextChange,
  documentProposalId,
  assistantRunning,
  assistantExpanded = false,
  libraryOpen = false,
  onLibraryClose,
  libraryReturnFocus,
  ideLibraryTarget,
  ideLibraryPreferred = false,
}) {
  const [semanticDirty, setSemanticDirty] = useState(false);
  const semanticLifecycle = useRef(null);
  const registerSemantic = useCallback((value) => { semanticLifecycle.current = value; }, []);
  const [pdfMounted, setPdfMounted] = useState(surface === 'pdf');
  useEffect(() => { if (surface === 'pdf') setPdfMounted(true); }, [surface]);
  const work = useWorkHub({
    threadId,
    assistantRunning,
    invalidationVersion,
    notify,
    onCancelRun,
    onThreadUnavailable,
    active,
    pdfActive: active && surface === 'pdf',
    libraryActive: libraryOpen,
  });
  useEffect(() => { onDirtyChange?.(work.dirty || semanticDirty); }, [onDirtyChange, work.dirty, semanticDirty]);
  const [section, setSection] = useState('workspace');
  const uploadSelection = useWorkUploadSelection({
    scope: threadId,
    disabled: !threadId,
    busy: Boolean(work.busy),
    onUpload: work.uploadToWorkspace,
    uploadOptions: libraryOpen ? LIBRARY_UPLOAD_OPTIONS : undefined,
  });
  const { open: contextOpen, setOpen: setContextOpen, ...contextSelection } = useWorkContextSelection(threadId);
  const contextButtonRef = useRef(null);
  const editorRef = useRef(null);
  const layout = useWorkbenchLayout();
  const { hub } = work;
  const workspace = hub.workspace || {};
  const ready = workspace.state === 'ready';
  const hasSelectedThread = Boolean(threadId) && workspace.state !== 'unselected';

  useEffect(() => {
    if (!threadId || workspace.state === 'unselected') setSection('workspace');
  }, [threadId, workspace.state]);

  const focusEditor = useCallback(() => {
    queueMicrotask(() => editorRef.current?.focus?.());
  }, []);
  const abandonDraft = work.abandonDraft;

  useEffect(() => onRegisterDraftLifecycle?.({
    abandon: async () => {
      if (await abandonDraft() === false) return false;
      return semanticLifecycle.current?.abandon?.() ?? true;
    },
    editorRef,
  }), [onRegisterDraftLifecycle, abandonDraft]);

  const openWorkspaceFile = useCallback((path, options = {}) => {
    if (path === work.file.path && !work.file.error && !options.onOpened) {
      focusEditor();
      return true;
    }
    const action = async () => {
      const opened = await work.openFile(path);
      if (opened) { focusEditor(); options.onOpened?.(); }
      else options.onFailed?.();
      return opened;
    };
    if (onRequestNavigation) {
      return onRequestNavigation(action, { returnFocus: document.activeElement });
    }
    if (work.dirty || semanticDirty) return false;
    return action();
  }, [focusEditor, onRequestNavigation, semanticDirty, work]);

  const uploadProps = {
    disabled: !threadId,
    busy: Boolean(work.busy),
    session: uploadSelection,
  };
  const uploadControl = !libraryOpen && <WorkFileUpload {...uploadProps} />;
  const compactUpload = !libraryOpen && <WorkFileUpload {...uploadProps} compact />;
  const context = () => (
    <WorkContextPanel
      room={hub.room}
      history={hub.history}
      file={work.file}
      busy={work.busy}
      onCreateIssue={work.createIssue}
      issueDraft={work.issueDraft}
      onUpdateIssue={work.updateIssue}
      onPreviewRevert={work.previewRevert}
      onControl={work.controlAgent}
      selectedTab={contextSelection.tab}
      onTabChange={contextSelection.selectTab}
    />
  );
  return (
    <>
    <WorkbenchLibraryDrawer work={{ ...work, threadId }} uploadSession={uploadSelection}
      ideTarget={ideLibraryTarget} preferIde={ideLibraryPreferred}
      isOpen={libraryOpen} onClose={onLibraryClose} finalFocusRef={libraryReturnFocus}
      blocked={Boolean(work.dirty || semanticDirty || assistantRunning || work.document.busy)} />
    {pdfMounted && <Box display={surface === 'pdf' ? 'flex' : 'none'} flex="1" minH={0} minW={0}>
      <PdfStudio work={{ ...work, threadId }} active={active && surface === 'pdf'} assistantRef={assistantRef}
        onOpenFile={openWorkspaceFile} onContextChange={onDocumentContextChange}
        onDirtyChange={setSemanticDirty} onRegister={registerSemantic} proposalId={documentProposalId}
        assistantRunning={assistantRunning} assistantExpanded={assistantExpanded} />
    </Box>}
    <Tabs
      display={surface === 'work' ? 'flex' : 'none'}
      index={layout === 'mobile' ? SECTIONS.indexOf(section) : 0}
      onChange={(index) => setSection(SECTIONS[index])}
      isFitted
      colorScheme="blue"
      data-testid="work-hub"
      data-workspace-state={workspace.state || 'unknown'}
      h="100%"
      flex="1"
      minH={0}
      minW={0}
      flexDirection="column"
      overflow="hidden"
      bg={WORK_HUB_THEME.pageBg}
    >
      <WorkStatusRail
        workspace={workspace}
        room={hub.room}
        file={work.file}
        dirty={work.dirty}
        section={section}
        refreshing={hub.loading || hub.refreshing}
        onRefresh={() => work.load({ background: true })}
        showContextAction={ready && layout === 'medium'}
        contextButtonRef={contextButtonRef}
        onOpenContext={() => setContextOpen(true)}
      />

      <Box
        data-testid={layout === 'mobile' ? 'work-mobile-tabs' : undefined}
        display={layout === 'mobile' ? 'block' : 'none'}
        flexShrink={0}
        bg={WORK_HUB_THEME.headerBg}
        borderBottom={`1px solid ${colors.border.subtle}`}
      >
        <TabList overflow="hidden" aria-label="Разделы работы">
          <Tab minW={0} fontSize="12px">Файлы</Tab>
          <Tab minW={0} fontSize="12px">Контекст</Tab>
        </TabList>
      </Box>

      <Flex flex="1" minH={0} minW={0} align="stretch">
          {layout !== 'mobile' && <Box
            key="work-source-rail"
            w={{ md: '260px', lg: '280px', xl: '300px' }}
            minW={0}
            flexShrink={0}
            borderRight={`1px solid ${WORK_HUB_THEME.panelBorder}`}
            overflow="hidden"
          >
            <WorkSourceRail
              workspace={workspace}
              file={{ ...work.file, onSelect: openWorkspaceFile }}
              compactUpload={compactUpload}
            />
          </Box>}

          <TabPanels key="work-main" flex="1" minW={0} minH={0} overflow="hidden">
            <TabPanel p={0} h="full">
              {ready ? (
                <Flex h="full" direction="column" minH={0}>
                  {layout === 'mobile' && <Box
                    h={work.file.path ? '34%' : '100%'}
                    minH={work.file.path ? '132px' : 0}
                    borderBottom={work.file.path ? `1px solid ${colors.border.subtle}` : '0'}
                  >
                    <VStack h="full" align="stretch" spacing={2} p={3}>
                      {section === 'workspace' ? compactUpload : null}
                      <Box flex="1" minH={0}>
                        <WorkspaceTree
                          entries={workspace.entries || []}
                          selected={work.file.path}
                          onSelect={openWorkspaceFile}
                          disabled={work.file.loading}
                        />
                      </Box>
                    </VStack>
                  </Box>}
                  <Box
                    display={layout !== 'mobile' || work.file.path ? 'block' : 'none'}
                    flex="1"
                    minW={0}
                    minH={0}
                  >
                    <WorkFileEditor work={work} editorRef={editorRef} />
                  </Box>
                </Flex>
              ) : (
                <WorkLanding
                  state={workspace.state}
                  hasThread={hasSelectedThread}
                  busy={work.busy}
                  loading={hub.loading || hub.refreshing}
                  onActivate={work.activateWorkspace}
                  onRetry={() => work.load()}
                  uploadControl={uploadControl}
                />
              )}
            </TabPanel>
            <TabPanel
              p={0}
              h="full"
              minW={0}
            >
              {context()}
            </TabPanel>
          </TabPanels>

          {ready && layout === 'wide' && (
            <Box
              key="work-context-panel"
              w="300px"
              minW={0}
              flexShrink={0}
              borderLeft={`1px solid ${WORK_HUB_THEME.panelBorder}`}
              overflow="hidden"
            >
              {context()}
            </Box>
          )}
      </Flex>

      {layout === 'medium' && (
        <WorkContextDrawer
          isOpen={contextOpen && active && surface === 'work'}
          onClose={() => setContextOpen(false)}
          finalFocusRef={contextButtonRef}
        >
          {context()}
        </WorkContextDrawer>
      )}
    </Tabs>
    </>
  );
}
