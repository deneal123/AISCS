import React, { memo, useCallback } from 'react';
import { VStack } from '@chakra-ui/react';
import TraceSessionCard from './TraceSessionCard';

function TracePanelComponent({ sessions, expandedMap, isCompactTrace, onToggleExpanded, onRunMode, isLoading, stopHint, layout }) {
  const handleToggle = useCallback((sessionId, expanded) => {
    onToggleExpanded(sessionId, expanded);
  }, [onToggleExpanded]);

  return (
    <VStack align="stretch" spacing={3} w="100%" minH={0}
      flex={layout === 'workbench' ? '1' : undefined}>
      {sessions.map((session) => (
        <TraceSessionCard
          key={session.id}
          session={session}
          isCompactTrace={isCompactTrace}
          isExpanded={expandedMap[session.id] ?? (session.status === 'running')}
          onToggleExpanded={(expanded) => handleToggle(session.id, expanded)}
          onRunMode={onRunMode}
          isLoading={isLoading}
          stopHint={stopHint}
          layout={layout}
        />
      ))}
    </VStack>
  );
}

const TracePanel = memo(TracePanelComponent);

export default TracePanel;
