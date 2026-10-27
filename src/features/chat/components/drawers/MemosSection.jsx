import { useId, useMemo, useState } from 'react';
import { Box, Button, HStack, Icon, Text, VStack } from '@chakra-ui/react';
import { FiArchive, FiChevronDown, FiChevronUp } from '@shared/icons';
import Pager from '@shared/controls/Pager';
import { borderRadius, colors } from '@theme/tokens';
import { CHAT_THEME } from '../../constants/theme';
import { extractMemosMemories, memoryDisplayText } from './memoryPresentation';

function MemoryRecord({ text, index }) {
  const [expanded, setExpanded] = useState(false);
  const id = useId();
  const display = useMemo(() => memoryDisplayText(text), [text]);
  const long = display.length > 240 || display.split('\n').length > 4;
  return <Box p={3} border="1px solid" borderColor={colors.border.subtle} borderRadius={borderRadius.md} minW={0}>
    <Text fontSize="xs" color={colors.text.tertiary} mb={2}>Запись {index + 1}</Text>
    <Box id={id} maxH={expanded ? '260px' : undefined} overflowY={expanded ? 'auto' : undefined}
      tabIndex={expanded && long ? 0 : undefined} role={expanded && long ? 'region' : undefined}
      aria-label={expanded && long ? `Полный текст записи ${index + 1}` : undefined}>
      <Text fontSize="sm" color={colors.text.secondary} lineHeight="1.6" whiteSpace="pre-wrap"
        overflowWrap="anywhere" noOfLines={long && !expanded ? 4 : undefined}>
        {display}
      </Text>
    </Box>
    {long && <Button mt={2} size="sm" minH="44px" variant="ghost" px={2}
      aria-expanded={expanded} aria-controls={id} onClick={() => setExpanded(value => !value)}>
      {expanded ? 'Свернуть запись' : 'Читать запись'}
    </Button>}
  </Box>;
}

/** Скрытие блока и чтение полной записи — отдельные независимые действия. */
export default function MemosSection({ dashboard }) {
  const [open, setOpen] = useState(true);
  const [page, setPage] = useState(0);
  const id = useId();
  const memories = useMemo(() => extractMemosMemories(dashboard).reverse(), [dashboard]);
  if (!memories.length) return null;
  const count = Math.ceil(memories.length / 5);
  const current = Math.min(page, count - 1);
  return <Box mb={4} borderRadius={borderRadius.md} bg={CHAT_THEME.panelBg}
    border="1px solid" borderColor={colors.border.subtle} overflow="hidden">
    <HStack as="button" type="button" w="full" minH="56px" p={3} spacing={2} textAlign="left"
      aria-expanded={open} aria-controls={id} onClick={() => setOpen(value => !value)}
      aria-label={open ? 'Скрыть семантическую память' : 'Раскрыть семантическую память'}
      _hover={{ bg: CHAT_THEME.panelHover }} _focusVisible={{ outline: '2px solid', outlineColor: colors.border.focus, outlineOffset: '-2px' }}>
      <Icon as={FiArchive} boxSize="16px" flexShrink={0} color={colors.spectral.amber} />
      <Box flex="1" minW={0}>
        <Text fontSize="sm" fontWeight="600">Семантическая память</Text>
        <Text fontSize="xs" color={colors.text.tertiary}>MemOS · записей: {memories.length}</Text>
      </Box>
      <Icon as={open ? FiChevronUp : FiChevronDown} boxSize="16px" flexShrink={0} />
    </HStack>
    <Box id={id} hidden={!open}>
      {open && <VStack align="stretch" spacing={3} px={3} pb={3}>
        {memories.slice(current * 5, current * 5 + 5).map((text, index) => (
          <MemoryRecord key={`${current}:${index}:${text}`} text={text} index={current * 5 + index} />
        ))}
        <Pager page={current} pageCount={count} onChange={setPage} />
      </VStack>}
    </Box>
  </Box>;
}
