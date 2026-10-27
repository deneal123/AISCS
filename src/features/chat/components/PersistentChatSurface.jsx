import React, { useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Box, Button, HStack, Text, VStack } from '@chakra-ui/react';
import ChatComposerPanel from './composer/ChatComposerPanel';
import ChatMessagesArea from './ChatMessagesArea';
import DocumentAssistantActivity from './DocumentAssistantActivity';
import { useDocumentAssistant } from '../hooks/useDocumentAssistant';
import IdeAssistantResult from './IdeAssistantResult';
import HumanQuestionPanel from './HumanQuestionPanel';
import { useHumanQuestion } from '../hooks/useHumanQuestion';

/** Move one DOM host, never reparent React's composer/recording/trace owners. */
export default function PersistentChatSurface({ target, chat, documentMode = false, ideMode = false, onDockExpandedChange }) {
  const workbench = documentMode || ideMode;
  const [host] = useState(() => document.createElement('div'));
  const [detailsOpen, setDetailsOpen] = useState(false);
  const activity = useDocumentAssistant(chat.messages);
  const question = useHumanQuestion({ threadId: chat.threadId, accountId: chat.accountId, surface: ideMode ? 'ide' : 'pdf',
    messages: chat.messages.visibleMessages, context: ideMode ? chat.ideContext : chat.documentContext,
    active: workbench, onAccepted: chat.onQuestionAccepted, onSettled: chat.onQuestionSettled });
  const dockExpanded = Boolean(workbench && (activity.tracing || question.blocking || detailsOpen));
  useLayoutEffect(() => {
    onDockExpandedChange?.(dockExpanded);
  }, [dockExpanded, onDockExpandedChange]);
  const wasTracing = useRef(false);
  const wasQuestion = useRef(false);
  const wasDetails = useRef(false);
  useLayoutEffect(() => {
    if (workbench && !question.blocking && !activity.tracing && !detailsOpen && (wasTracing.current || wasQuestion.current || wasDetails.current)
      && (document.activeElement === document.body
        || document.activeElement?.closest('[data-testid="document-assistant-activity"], [data-testid="human-question-panel"]'))) {
      chat.composerRef?.current?.focus?.();
    }
    wasTracing.current = activity.tracing;
    wasQuestion.current = question.blocking;
    wasDetails.current = detailsOpen;
  }, [activity.tracing, question.blocking, detailsOpen, chat.composerRef, workbench]);
  useLayoutEffect(() => {
    host.style.cssText = 'display:flex;flex-direction:column;flex:1;min-width:0;min-height:0;overflow:hidden';
    target?.appendChild(host);
    // The same composer keeps its draft, but its destination may have a different
    // width. Resolve compact controls in this commit, before the browser paints.
    chat.composerRef?.current?.refreshLayout?.();
    return () => host.remove();
  }, [host, target, chat.composerRef]);
  return createPortal(
    <VStack flex="1" minH={0} minW={0} align="stretch" spacing={0} overflowX="hidden"
      overflowY={workbench && !activity.tracing && !question.blocking && !detailsOpen ? 'auto' : 'hidden'}>
      <Box display={workbench ? 'none' : 'contents'}>
        {!workbench && <ChatMessagesArea {...chat.messages} />}
      </Box>
      {ideMode && chat.idePreparing && <HStack px={3} py={2} flexShrink={0}>
        <Text fontSize="xs" role="status" flex="1">Проверяю репозиторий перед отправкой…</Text>
        <Button size="document" variant="ghost" onClick={chat.onCancelIdePreparation}>Отменить</Button>
      </HStack>}
      {question.blocking ? <HumanQuestionPanel state={question} ideMode={ideMode} onStop={chat.composer.onStop} />
        : workbench && <DocumentAssistantActivity state={activity} messages={chat.messages} variant={ideMode ? 'ide' : 'document'}
          onDetailsChange={setDetailsOpen}
          notice={question.notice} onStop={chat.composer.onStop} onOpenChat={chat.onOpenChat} />}
      {ideMode && !activity.tracing && !question.question && !detailsOpen && <IdeAssistantResult messages={chat.messages.visibleMessages} composerRef={chat.composerRef} />}
      <Box display={workbench && (activity.tracing || question.blocking || detailsOpen) ? 'none' : 'contents'}>
        <ChatComposerPanel ref={chat.composerRef} {...chat.composer} documentMode={documentMode}
          workbenchMode={workbench} hintPaused={activity.waiting}
          visible={!workbench || (!activity.tracing && !question.blocking && !detailsOpen)} />
      </Box>
    </VStack>,
    host,
  );
}
