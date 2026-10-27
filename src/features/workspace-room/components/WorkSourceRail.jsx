import { Box, Divider, HStack, Icon, Text, VStack } from '@chakra-ui/react';
import { FiFolder } from '@shared/icons';
import { colors } from '@theme/tokens';
import { WorkspaceTree } from './WorkspaceTree';

export function WorkSourceRail({ workspace, file, compactUpload }) {
  const ready = workspace.state === 'ready';
  return <VStack h="full" align="stretch" spacing={0}>
    <HStack px={3} py={3} spacing={2} flexShrink={0}>
      <Icon as={FiFolder} boxSize={4} /><Text fontSize="13px" fontWeight={600}>Рабочее место</Text>
    </HStack>
    <Divider borderColor={colors.border.subtle} />
    <Box flex="1" minH={0} overflow="hidden" p={3}>
      {ready ? <VStack align="stretch" h="full" spacing={3}>
        <Box flexShrink={0}>{compactUpload}</Box>
        <Box flex="1" minH={0}>
          <WorkspaceTree entries={workspace.entries || []} selected={file.path}
            onSelect={file.onSelect} disabled={file.loading} />
        </Box>
      </VStack> : <Text fontSize="11.5px" lineHeight="1.55" color={colors.fg[4]}>
        Рабочая среда появится после явного создания или загрузки. Библиотека файлов — в левой панели.
      </Text>}
    </Box>
  </VStack>;
}
