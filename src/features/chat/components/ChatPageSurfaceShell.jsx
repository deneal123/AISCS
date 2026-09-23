import React, { lazy, Suspense } from 'react';
import { Flex, VStack } from '@chakra-ui/react';
import ChatComposerPanel from './composer/ChatComposerPanel';
import ChatHeaderBar from './ChatHeaderBar';
import ChatMessagesArea from './ChatMessagesArea';

const WorkHub = lazy(() => import('@features/workspace-room').then((module) => ({
  default: module.WorkHub,
})));

/**
 * Owns the persistent Chat/Work peer-surface layout and its scroll boundaries.
 * Data orchestration stays in ChatPageContainer, while this component guarantees
 * that mounting Work does not tear down Chat and background refresh cannot move
 * the header or sidebar.
 */
export default function ChatPageSurfaceShell({ sidebar, header, work, chat }) {
  return (
    <Flex h="100%" overflow="hidden" position="relative" zIndex={1}>
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
            <Suspense fallback={null}>
              <WorkHub {...work.props} active={work.active} />
            </Suspense>
          </Flex>
        )}

        <VStack
          display={work.active ? 'none' : 'flex'}
          flex="1"
          minH={0}
          align="stretch"
          spacing={0}
          overflow="hidden"
        >
          <ChatMessagesArea {...chat.messages} />
          <ChatComposerPanel ref={chat.composerRef} {...chat.composer} />
        </VStack>
      </VStack>
    </Flex>
  );
}
