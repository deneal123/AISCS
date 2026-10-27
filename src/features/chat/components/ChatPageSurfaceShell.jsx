import React, { lazy, Suspense, useEffect, useState } from 'react';
import { Flex, VStack } from '@chakra-ui/react';
import ChatWorkLoading from './ChatWorkLoading';
import ChatHeaderBar from './ChatHeaderBar';
import PersistentChatSurface from './PersistentChatSurface';

const WorkHub = lazy(() => import('@features/workspace-room').then((module) => ({
  default: module.WorkHub,
})));
const IdeStudio = lazy(() => import('@features/workspace-room').then((module) => ({ default: module.IdeStudio })));

/**
 * Owns the persistent Chat/Work peer-surface layout and its scroll boundaries.
 * Data orchestration stays in ChatPageContainer, while this component guarantees
 * that mounting Work does not tear down Chat and background refresh cannot move
 * the header or sidebar.
 */
export default function ChatPageSurfaceShell({ sidebar, header, work, chat }) {
  const composer = chat.composer || {};
  const [chatTarget, setChatTarget] = useState(null);
  const [pdfTarget, setPdfTarget] = useState(null);
  const [ideTarget, setIdeTarget] = useState(null);
  const [assistantExpanded, setAssistantExpanded] = useState(false);
  const ide = header.surface === 'work';
  const pdf = header.surface === 'pdf';
  const [ideMounted, setIdeMounted] = useState(header.surface === 'work');
  const [hubMounted, setHubMounted] = useState(pdf || Boolean(work.props.libraryOpen));
  useEffect(() => { if (header.surface === 'work') setIdeMounted(true); }, [header.surface]);
  useEffect(() => { if (pdf || work.props.libraryOpen) setHubMounted(true); }, [pdf, work.props.libraryOpen]);
  return (
    <Flex h="100%" overflow="hidden" position="relative" zIndex={1}
      data-action-hints-paused={Boolean(composer.disabled || composer.isStreaming
        || composer.isFileUploading || composer.isRecording
        || composer.isRequestingPermission || composer.isVoiceTranscribing || composer.compacting)}>
      {sidebar.render(sidebar.collapsed, false)}

      <VStack flex="1" align="stretch" spacing={0} minH="0" overflow="hidden">
        <ChatHeaderBar {...header} />

        {work.mounted && (
          <Flex
            display={work.active ? 'flex' : 'none'}
            flex="1"
            minH={0}
            minW={0}
            overflow="hidden"
          >
            <Suspense fallback={<ChatWorkLoading {...work.props} />}>
              {hubMounted && <WorkHub key={work.props.threadId} {...work.props} active={work.active && pdf} surface={pdf ? 'pdf' : 'hidden'} assistantRef={setPdfTarget} assistantExpanded={assistantExpanded} />}
              {ideMounted && <IdeStudio key={`ide:${work.props.threadId}`} threadId={work.props.threadId} active={work.active && header.surface === 'work'}
                onDirtyChange={work.props.onDirtyChange} onRegisterDraftLifecycle={work.props.onRegisterDraftLifecycle} onRequestNavigation={work.props.onRequestNavigation}
                onThreadUnavailable={work.props.onThreadUnavailable}
                assistantRef={setIdeTarget} onContextChange={work.props.onIdeContextChange} assistantRunning={work.props.assistantRunning} />}
            </Suspense>
          </Flex>
        )}

        <VStack
          ref={setChatTarget}
          display={work.active ? 'none' : 'flex'}
          flex="1"
          minH={0}
          align="stretch"
          spacing={0}
          overflow="hidden"
        >
        </VStack>
        <PersistentChatSurface target={ide ? ideTarget : pdf && pdfTarget ? pdfTarget : chatTarget} chat={chat} documentMode={pdf} ideMode={ide} onDockExpandedChange={setAssistantExpanded} />
      </VStack>
    </Flex>
  );
}
