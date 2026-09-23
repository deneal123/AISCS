import { Box, Button, Divider, HStack, Text, VStack } from '@chakra-ui/react';
import { FiBookOpen, FiFolder } from '@shared/icons';
import { colors } from '@theme/tokens';
import { LibraryPane } from './LibraryPane';
import { WorkspaceTree } from './WorkspaceTree';

export function WorkSourceRail({
  section,
  onSectionChange,
  workspace,
  library,
  file,
  busy,
  hasThread,
  compactUpload,
  outcomes,
  onCopy,
  onLoadMore,
}) {
  const ready = workspace.state === 'ready';
  return (
    <VStack h="full" align="stretch" spacing={0}>
      <HStack p={3} spacing={1} flexShrink={0}>
        <Button
          size="sm"
          flex="1"
          justifyContent="flex-start"
          leftIcon={<FiFolder />}
          onClick={() => onSectionChange('workspace')}
          aria-pressed={section === 'workspace'}
          variant={section === 'workspace' ? 'solid' : 'ghost'}
          colorScheme={section === 'workspace' ? 'blue' : undefined}
        >
          Рабочее место
        </Button>
        <Button
          data-testid="work-library-nav"
          size="sm"
          flex="1"
          justifyContent="flex-start"
          leftIcon={<FiBookOpen />}
          onClick={() => onSectionChange('library')}
          aria-pressed={section === 'library'}
          variant={section === 'library' ? 'solid' : 'ghost'}
          colorScheme={section === 'library' ? 'blue' : undefined}
        >
          Библиотека
        </Button>
      </HStack>
      <Divider borderColor={colors.border.subtle} />
      <Box flex="1" minH={0} overflow="hidden" p={3}>
        <Box display={section === 'library' ? 'block' : 'none'} h="full">
          <LibraryPane
            items={library.items || []}
            state={library.state}
            workspaceReady={ready}
            hasThread={hasThread}
            busy={busy}
            onCopy={onCopy}
            onLoadMore={onLoadMore}
            hasMore={library.next_cursor != null || library.next_offset != null}
            uploadControl={section === 'library' ? compactUpload : null}
            outcomes={outcomes}
            compact
          />
        </Box>
        <Box display={section === 'workspace' ? 'block' : 'none'} h="full">
          {ready ? (
          <VStack align="stretch" h="full" spacing={3}>
            <Box flexShrink={0}>{section === 'workspace' ? compactUpload : null}</Box>
            <Box flex="1" minH={0}>
              <WorkspaceTree
                entries={workspace.entries || []}
                selected={file.path}
                onSelect={file.onSelect}
                disabled={file.loading}
              />
            </Box>
          </VStack>
        ) : (
          <Text fontSize="11.5px" lineHeight="1.55" color={colors.fg[4]}>
            Рабочая среда появится после явного создания или загрузки. Библиотека доступна отдельно.
          </Text>
          )}
        </Box>
      </Box>
    </VStack>
  );
}
