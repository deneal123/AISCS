import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Box,
  Flex,
  Tab,
  TabList,
  Tabs,
  VStack,
} from '@chakra-ui/react';
import { colors } from '@theme/tokens';
import { WORK_HUB_THEME } from '../model/theme';
import { useWorkHub } from '../model/useWorkHub';
import { useWorkbenchLayout } from '../model/useWorkbenchLayout';
import { LibraryPane } from './LibraryPane';
import { WorkContextDrawer } from './WorkContextDrawer';
import { WorkContextPanel } from './WorkContextPanel';
import { WorkFileUpload } from './WorkFileUpload';
import { WorkLanding } from './WorkLanding';
import { WorkSourceRail } from './WorkSourceRail';
import { WorkStatusRail } from './WorkStatusRail';
import { WorkspaceEditor } from './WorkspaceEditor';
import { WorkspaceTree } from './WorkspaceTree';

const SECTIONS = ['workspace', 'library', 'context'];

function Editor({ work, editorRef }) {
  return (
    <WorkspaceEditor
      file={work.file}
      dirty={work.dirty}
      busy={work.busy}
      conflict={work.conflict}
      revert={work.revert}
      onChange={(content) => work.setFile((old) => ({ ...old, content }))}
      onSave={work.save}
      onDiscard={work.discard}
      onReacquire={work.reacquireLease}
      onCopyDraft={work.copyDraft}
      onLoadActual={work.loadActual}
      onCloseRevert={() => work.setRevert(null)}
      onApplyRevert={work.applyRevert}
      editorRef={editorRef}
    />
  );
}

export default function WorkHub({
  threadId,
  invalidationVersion,
  notify,
  onCancelRun,
  onDirtyChange,
  onRequestNavigation,
  onRegisterDraftLifecycle,
  active = true,
}) {
  const work = useWorkHub({
    threadId,
    invalidationVersion,
    notify,
    onCancelRun,
    onDirtyChange,
    active,
  });
  const [section, setSection] = useState('workspace');
  const [contextOpen, setContextOpen] = useState(false);
  const contextButtonRef = useRef(null);
  const editorRef = useRef(null);
  const layout = useWorkbenchLayout();
  const { hub } = work;
  const workspace = hub.workspace || {};
  const libraryState = hub.library || {};
  const ready = workspace.state === 'ready';
  const hasSelectedThread = Boolean(threadId) && workspace.state !== 'unselected';

  useEffect(() => {
    if (!threadId || workspace.state === 'unselected') setSection('library');
  }, [threadId, workspace.state]);

  const focusEditor = useCallback(() => {
    queueMicrotask(() => editorRef.current?.focus?.());
  }, []);

  useEffect(() => onRegisterDraftLifecycle?.({
    abandon: work.abandonDraft,
    focusEditor,
  }), [focusEditor, onRegisterDraftLifecycle, work.abandonDraft]);

  const openWorkspaceFile = useCallback((path) => {
    if (path === work.file.path && !work.file.error) {
      focusEditor();
      return true;
    }
    const action = async () => {
      const opened = await work.openFile(path);
      if (opened) focusEditor();
      return opened;
    };
    if (onRequestNavigation) {
      return onRequestNavigation(action, { returnFocus: document.activeElement });
    }
    if (work.dirty) return false;
    action();
    return true;
  }, [focusEditor, onRequestNavigation, work]);

  const uploadControl = (
    <WorkFileUpload
      disabled={!threadId}
      busy={work.busy === 'upload'}
      onUpload={work.uploadToWorkspace}
      onPartial={() => setSection('library')}
    />
  );
  const compactUpload = (
    <WorkFileUpload
      disabled={!threadId}
      busy={Boolean(work.busy)}
      onUpload={work.uploadToWorkspace}
      onPartial={() => setSection('library')}
      compact
    />
  );
  const context = (
    <WorkContextPanel
      room={hub.room}
      history={hub.history}
      file={work.file}
      busy={work.busy}
      onCreateIssue={work.createIssue}
      onUpdateIssue={work.updateIssue}
      onPreviewRevert={work.previewRevert}
      onControl={work.controlAgent}
      document={work.document}
    />
  );
  const library = (
    <LibraryPane
      items={libraryState.items || []}
      state={libraryState.state}
      workspaceReady={ready}
      hasThread={hasSelectedThread}
      busy={work.busy}
      onCopy={work.copyFromLibrary}
      onLoadMore={work.loadMoreLibrary}
      hasMore={libraryState.next_cursor != null || libraryState.next_offset != null}
      uploadControl={layout === 'mobile' && section === 'library' ? uploadControl : null}
      outcomes={work.libraryOutcomes}
    />
  );

  return (
    <Flex
      data-testid="work-hub"
      data-workspace-state={workspace.state || 'unknown'}
      h="100%"
      flex="1"
      minH={0}
      minW={0}
      direction="column"
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

      {layout === 'mobile' && (
        <Box
          data-testid="work-mobile-tabs"
          flexShrink={0}
          bg={WORK_HUB_THEME.headerBg}
          borderBottom={`1px solid ${colors.border.subtle}`}
        >
          <Tabs
            index={SECTIONS.indexOf(section)}
            onChange={(index) => setSection(SECTIONS[index])}
            isFitted
            colorScheme="blue"
          >
            <TabList overflow="hidden">
              <Tab minW={0} fontSize="12px">Файлы</Tab>
              <Tab data-testid="work-library-nav" minW={0} fontSize="12px">
                Библиотека
              </Tab>
              <Tab minW={0} fontSize="12px">Контекст</Tab>
            </TabList>
          </Tabs>
        </Box>
      )}

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
              section={section === 'context' ? 'workspace' : section}
              onSectionChange={setSection}
              workspace={workspace}
              library={libraryState}
              file={{ ...work.file, onSelect: openWorkspaceFile }}
              busy={work.busy}
              hasThread={hasSelectedThread}
              compactUpload={compactUpload}
              outcomes={work.libraryOutcomes}
              onCopy={work.copyFromLibrary}
              onLoadMore={work.loadMoreLibrary}
            />
          </Box>}

          <Box key="work-main" flex="1" minW={0} minH={0} overflow="hidden">
            <Box display={layout !== 'mobile' || section === 'workspace' ? 'block' : 'none'} h="full">
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
                    <Editor work={work} editorRef={editorRef} />
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
                  uploadControl={section === 'library' ? null : uploadControl}
                />
              )}
            </Box>
            <Box
              display={layout === 'mobile' && section === 'library' ? 'block' : 'none'}
              h="full"
              minW={0}
              p={3}
            >
              {library}
            </Box>
            <Box
              display={layout === 'mobile' && section === 'context' ? 'block' : 'none'}
              h="full"
              minW={0}
            >
              {context}
            </Box>
          </Box>

          {ready && layout === 'wide' && (
            <Box
              key="work-context-panel"
              w="300px"
              minW={0}
              flexShrink={0}
              borderLeft={`1px solid ${WORK_HUB_THEME.panelBorder}`}
              overflow="hidden"
            >
              {context}
            </Box>
          )}
      </Flex>

      {layout === 'medium' && (
        <WorkContextDrawer
          isOpen={contextOpen}
          onClose={() => setContextOpen(false)}
          finalFocusRef={contextButtonRef}
        >
          {context}
        </WorkContextDrawer>
      )}
    </Flex>
  );
}
