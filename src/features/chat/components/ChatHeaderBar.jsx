import React from 'react';
import { Box, Button, Flex, HStack, IconButton, Text, Tooltip } from '@chakra-ui/react';
import { FiMenu, FiSettings } from '@shared/icons';
import { borderRadius, colors } from '@theme/tokens';
import { CreditsPill, useBillingContext } from '@features/billing';
import { CHAT_FONT_FAMILY, CHAT_THEME } from '../constants/theme';

const CONNECTION_META = {
  connected: { color: colors.success, label: 'На связи' },
  connecting: { color: colors.warning, label: 'Подключение…' },
  reconnecting: { color: colors.warning, label: 'Переподключение…' },
  error: { color: colors.error, label: 'Нет связи' },
  disconnected: { color: CHAT_THEME.textTertiary, label: 'Не подключено' },
};

/** Шапка чата: тоггл сайдбара, заголовок треда, статус соединения, настройки. */
export default function ChatHeaderBar({
  onOpenMobileSidebar,
  onToggleSidebar,
  threadTitle,
  connectionState,
  onOpenSettings,
  surface = 'chat',
  onSurfaceChange,
}) {
  const iconBtnProps = {
    variant: 'ghost',
    size: 'sm',
    color: CHAT_THEME.textSecondary,
    _hover: { bg: CHAT_THEME.panelHover, color: CHAT_THEME.textPrimary },
    borderRadius: borderRadius.sm,
    boxSize: { base: '44px', md: '32px' },
    minW: { base: '44px', md: '32px' },
    h: { base: '44px', md: '32px' },
  };

  const conn = CONNECTION_META[connectionState] || CONNECTION_META.disconnected;
  const { balance } = useBillingContext();

  return (
    <Flex
      as="header"
      align="center"
      gap={2}
      px={{ base: 3, md: 5 }}
      h={{ base: '64px', md: '56px' }}
      flexShrink={0}
      borderBottom={`1px solid ${CHAT_THEME.panelBorder}`}
      bg={CHAT_THEME.headerBg}
      backdropFilter="blur(22px)"
    >
      <HStack spacing={1} flexShrink={0}>
        <IconButton aria-label="Меню" icon={<FiMenu />} display={{ base: 'inline-flex', lg: 'none' }}
          onClick={onOpenMobileSidebar} {...iconBtnProps} />
        <IconButton aria-label="Переключить сайдбар" icon={<FiMenu />} display={{ base: 'none', lg: 'inline-flex' }}
          onClick={onToggleSidebar} {...iconBtnProps} />
      </HStack>

      <HStack flex="1" minW={0} spacing={2}>
        <Tooltip label={conn.label} placement="bottom" openDelay={200} hasArrow>
          <Box
            boxSize="8px"
            borderRadius="full"
            bg={conn.color}
            boxShadow={connectionState === 'connected' ? `0 0 8px ${conn.color}` : 'none'}
            aria-label={conn.label}
            role="status"
            flexShrink={0}
          />
        </Tooltip>
        <Text
          flex="1"
          minW={0}
          noOfLines={1}
          fontSize="14px"
          fontWeight="650"
          letterSpacing="-0.01em"
          color={CHAT_THEME.textPrimary}
          fontFamily={CHAT_FONT_FAMILY}
        >
          {threadTitle || 'Новый чат'}
        </Text>
      </HStack>

      <HStack spacing={1} flexShrink={0} p="2px" borderRadius={borderRadius.sm} bg={CHAT_THEME.inputBg}>
        <Button size="xs" h="28px" px={3} variant={surface === 'chat' ? 'solid' : 'ghost'} colorScheme={surface === 'chat' ? 'blue' : undefined}
          onClick={() => onSurfaceChange?.('chat')}>Чат</Button>
        <Button size="xs" h="28px" px={3} variant={surface === 'work' ? 'solid' : 'ghost'} colorScheme={surface === 'work' ? 'blue' : undefined}
          onClick={() => onSurfaceChange?.('work')}>Работа</Button>
      </HStack>

      <HStack spacing={2} flexShrink={0} justify="flex-end">
        <Box display={{ base: 'none', sm: 'block' }}>
          <CreditsPill total={balance?.total} />
        </Box>
        <IconButton
          aria-label="Настройки чата"
          icon={<FiSettings />}
          onClick={onOpenSettings}
          {...iconBtnProps}
          borderRadius="full"
        />
      </HStack>
    </Flex>
  );
}
