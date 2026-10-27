import { useRef } from 'react';
import { Box, Button, Icon, Popover, PopoverBody, PopoverCloseButton, PopoverContent,
  PopoverHeader, PopoverTrigger, Portal, Text, VisuallyHidden, useDisclosure } from '@chakra-ui/react';
import { FiAlertCircle, FiCheckCircle } from '@shared/icons';
import { borderRadius, colors, layers } from '@theme/tokens';

/** Fixed-size toolbar slot. Diagnostics never participate in workbench geometry. */
export default function IdeStatusNotices({ notices, recovery, activity }) {
  const close = useRef(null);
  const { isOpen, onOpen, onClose } = useDisclosure();
  const count = notices.length + Number(Boolean(recovery));
  return <Popover placement="bottom-end" initialFocusRef={close} isLazy isOpen={isOpen} onOpen={onOpen} onClose={onClose}>
    <PopoverTrigger><Button size="document" variant="ghost" w="34px" minW="34px" px={0}
      aria-label="Состояние IDE" onClick={onOpen} title={count ? `Состояние IDE: ${count} уведомлений` : 'Состояние IDE'}>
      <Icon as={count ? FiAlertCircle : FiCheckCircle} boxSize={3.5} color={count ? colors.warning : colors.fg[3]} />
    </Button></PopoverTrigger>
    <VisuallyHidden role="status">{count ? `Уведомлений IDE: ${count}` : 'Нет предупреждений IDE'}</VisuallyHidden>
    <Portal><PopoverContent w="360px" maxW="calc(100vw - 24px)" maxH="min(440px, 70dvh)"
      bg={colors.bg.menu} borderColor={colors.border.strong} borderRadius={borderRadius.md}
      zIndex={layers.popover} overflow="hidden" display="flex" flexDirection="column">
      <PopoverHeader pr={10} fontSize="sm" fontWeight={600} flexShrink={0}>Состояние IDE</PopoverHeader>
      <PopoverCloseButton ref={close} aria-label="Закрыть состояние IDE" />
      <PopoverBody overflowY="auto" minH={0} fontSize="xs">
        {activity && <Text role="status" mb={2} color={colors.fg[3]}>{activity}</Text>}
        {notices.map(notice => <Box key={notice.id} py={2} borderBottom="1px solid" borderColor={colors.border.subtle}>
          <Text color={colors.fg[2]}>{notice.label}</Text>
          {notice.onRetry && <Button mt={1} size="document" variant="ghost" onClick={notice.onRetry}>{notice.action || 'Повторить чтение'}</Button>}
        </Box>)}
        {recovery}
        {!count && !activity && <Text color={colors.fg[3]}>Нет предупреждений.</Text>}
      </PopoverBody>
    </PopoverContent></Portal>
  </Popover>;
}
