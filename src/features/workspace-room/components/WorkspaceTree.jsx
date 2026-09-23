import { HStack, Icon, Text, VStack } from '@chakra-ui/react';
import { FiFileText, FiFolder } from '@shared/icons';
import { borderRadius, colors } from '@theme/tokens';
import { WORK_HUB_THEME, WORK_SCROLLBAR_SX } from '../model/theme';

const size = (value) => {
  const number = Number(value || 0);
  if (!number) return '';
  return number < 1024 ? `${number} Б` : `${Math.round(number / 1024)} КБ`;
};

export function WorkspaceTree({ entries = [], selected, onSelect, disabled }) {
  return (
    <VStack align="stretch" spacing={0.5} overflow="auto" sx={WORK_SCROLLBAR_SX} h="full">
      {entries.length === 0 && <Text px={3} py={4} fontSize="12px" color={colors.fg[4]}>Каталог пока пуст.</Text>}
      {entries.map((item) => {
        const isFile = item.type === 'file';
        return (
          <HStack key={item.path} data-testid={isFile ? 'workspace-file' : 'workspace-directory'}
            data-workspace-path={item.path} as={isFile ? 'button' : 'div'} type={isFile ? 'button' : undefined}
            onClick={isFile ? () => onSelect(item.path) : undefined} disabled={disabled || !isFile}
            px={3} py={2} spacing={2} minW={0} textAlign="left" borderRadius={borderRadius.sm}
            bg={selected === item.path ? WORK_HUB_THEME.accentSoft : 'transparent'}
            _hover={isFile ? { bg: WORK_HUB_THEME.panelHover } : undefined}
            _focusVisible={{ outline: `2px solid ${colors.border.focus}` }}>
            <Icon as={isFile ? FiFileText : FiFolder} boxSize="14px" color={isFile ? colors.fg[4] : colors.iris[300]} flexShrink={0} />
            <Text flex="1" minW={0} noOfLines={1} fontSize="12.5px" color={colors.fg[2]}>{item.path}</Text>
            <Text fontSize="10px" color={colors.fg[4]}>{size(item.size)}</Text>
          </HStack>
        );
      })}
    </VStack>
  );
}
