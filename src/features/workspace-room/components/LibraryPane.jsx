import { useEffect, useState } from 'react';
import { Badge, Box, Button, HStack, Icon, Text, VStack } from '@chakra-ui/react';
import { FiCopy, FiFileText } from '@shared/icons';
import { borderRadius, colors } from '@theme/tokens';
import { WORK_HUB_THEME, WORK_SCROLLBAR_SX } from '../model/theme';

const isAvailable = (item) => !item.availability || item.availability === 'ready';

const OUTCOME_LABELS = {
  imported: 'добавлен',
  kept: 'сохранён без перезаписи',
  conflict: 'нужно обновить',
  busy: 'занято агентом',
  unavailable: 'временно недоступно',
};

const outcomeScheme = (outcome) => {
  if (outcome === 'imported') return 'green';
  if (outcome === 'conflict' || outcome === 'busy') return 'orange';
  if (outcome === 'unavailable') return 'red';
  return 'gray';
};

export function LibraryPane({
  items = [],
  state = 'ready',
  workspaceReady,
  hasThread,
  busy,
  onCopy,
  onLoadMore,
  hasMore,
  uploadControl,
  outcomes = {},
}) {
  const [selectedId, setSelectedId] = useState('');

  useEffect(() => {
    if (selectedId && !items.some((item) => item.file_id === selectedId)) {
      setSelectedId('');
    }
  }, [items, selectedId]);

  return (
    <VStack align="stretch" spacing={2} h="full" overflow="auto" sx={WORK_SCROLLBAR_SX}>
      <Box px={3} py={2.5} borderRadius={borderRadius.md} bg={colors.accent.softest} border={`1px solid ${colors.accent.subtleBorder}`}>
        <Text fontSize="11.5px" color={colors.fg[3]}>Библиотека постоянна. Новый файл сохраняется здесь и отдельной копией добавляется во временное рабочее место.</Text>
      </Box>
      {uploadControl}
      {state === 'unavailable' && (
        <Box px={3} py={2.5} borderRadius={borderRadius.md} bg={colors.warningSoft} border={`1px solid ${colors.warningBorder}`}>
          <Text fontSize="11.5px" color={colors.fg[3]}>Библиотека временно недоступна. Рабочее место можно продолжать использовать.</Text>
        </Box>
      )}
      {state === 'stale' && (
        <Text fontSize="11px" color={colors.warning}>Показаны последние доступные данные библиотеки.</Text>
      )}
      {state !== 'unavailable' && items.length === 0 && (
        <Text py={4} fontSize="12.5px" color={colors.fg[4]}>В библиотеке пока нет доступных файлов.</Text>
      )}
      {items.map((item) => (
        <Box
          key={item.file_id}
          data-testid="work-library-file"
          data-selected={selectedId === item.file_id ? 'true' : 'false'}
          px={3}
          py={2.5}
          borderRadius={borderRadius.md}
          bg={selectedId === item.file_id ? colors.accent.softest : WORK_HUB_THEME.panelBg}
          border={`1px solid ${
            selectedId === item.file_id ? colors.accent.subtleBorder : colors.border.subtle
          }`}
        >
          <HStack spacing={2} minW={0}>
            <Icon as={FiFileText} color={colors.iris[300]} boxSize="14px" flexShrink={0} />
            <Text flex="1" minW={0} noOfLines={1} fontSize="12.5px" color={colors.fg[2]}>{item.name}</Text>
            <Badge colorScheme="blue" fontSize="9px">библиотека</Badge>
          </HStack>
          <HStack mt={1.5} spacing={2}>
            <Text fontSize="10px" color={colors.fg[4]}>
              {item.file_type || 'файл'} · {isAvailable(item) ? 'доступен' : 'недоступен'}
            </Text>
            {outcomes[item.file_id] && (
              <Badge colorScheme={outcomeScheme(outcomes[item.file_id])}>
                {OUTCOME_LABELS[outcomes[item.file_id]] || 'статус обновлён'}
              </Badge>
            )}
          </HStack>
          <Button mt={2.5} w="full" size="xs" leftIcon={<FiCopy />} onClick={() => {
            setSelectedId(item.file_id);
            onCopy(item);
          }}
            onFocus={() => setSelectedId(item.file_id)}
            isLoading={busy === `copy:${item.file_id}`}
            isDisabled={!hasThread || Boolean(busy) || !isAvailable(item)}
            variant="outline" color={colors.blue[300]} borderColor={colors.accent.subtleBorder}
            _hover={{ bg: colors.accent.hoverSoft }}>
            {workspaceReady ? 'Добавить в рабочее место' : 'Создать и добавить'}
          </Button>
        </Box>
      ))}
      {hasMore && (
        <Button size="sm" variant="ghost" onClick={onLoadMore} isLoading={busy === 'library:more'} isDisabled={Boolean(busy)}>
          Показать ещё
        </Button>
      )}
    </VStack>
  );
}
