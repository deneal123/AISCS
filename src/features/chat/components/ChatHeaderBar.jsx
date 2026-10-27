import React from 'react';
import { Box, Button, Grid, HStack, IconButton, Text, Tooltip } from '@chakra-ui/react';
import { FiMenu, FiSettings } from '@shared/icons';
import { borderRadius, colors } from '@theme/tokens';
import { CreditsPill, useBillingContext } from '@features/billing';
import { CHAT_FONT_FAMILY, CHAT_THEME } from '../constants/theme';
import ProviderAvailability from './ProviderAvailability';
import { useResponsive } from '@hooks/useResponsive';

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
  const { isMobile } = useResponsive();
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
  const separator = {
    content: '""', position: 'absolute', left: 0, top: '50%', transform: 'translateY(-50%)',
    h: '20px', borderLeft: `1px solid ${CHAT_THEME.panelBorder}`,
    display: { base: 'none', md: 'block' },
  };

  return (
    <Grid
      as="header"
      alignItems="center"
      templateAreas={{ base: '"identity account"', md: '"identity navigation account"' }}
      templateColumns={{ base: 'minmax(0, 1fr) auto', md: 'minmax(80px, 1fr) auto auto' }}
      columnGap="12px"
      rowGap={1}
      px={{ base: 3, md: 5 }}
      h="56px"
      flexShrink={0}
      borderBottom={`1px solid ${CHAT_THEME.panelBorder}`}
      bg={CHAT_THEME.headerBg}
      backdropFilter="blur(22px)"
    >
      <HStack gridArea="identity" spacing={1} minW={0}>
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
      </HStack>

      {!isMobile && <HStack gridArea="navigation" justifySelf="start" spacing="8px">
        <HStack role="group" aria-label="Разделы треда" spacing="4px">
          {[['chat', 'Чат'], ['work', 'IDE'], ['pdf', 'PDF']].map(([value, label]) => (
            <Button key={value} size="document" h="30px" minH="30px" px="12px"
              variant="ghost" borderRadius={borderRadius.control}
              data-thread-surface={value} data-action-hint={surface !== value ? 'hover' : undefined}
              bg="transparent" border="1px solid" overflow="visible"
              borderColor={surface === value ? colors.glass.borderHi : 'transparent'}
              _hover={{ bg: CHAT_THEME.panelHover, color: colors.fg[1] }}
              _active={{ bg: CHAT_THEME.panelActive }}
              color={surface === value ? colors.fg[1] : colors.fg[2]}
              aria-pressed={surface === value} onClick={() => onSurfaceChange?.(value)}>{label}</Button>
          ))}
        </HStack>
        <Box display="flex" alignItems="center" h="30px" position="relative"
          pl={{ base: 0, md: '12px' }} _before={separator}>
          <ProviderAvailability />
        </Box>
      </HStack>}

      <HStack gridArea="account" role="group" aria-label="Баланс и настройки" spacing={2}
        justify="flex-end" h={{ base: '44px', md: '30px' }} position="relative"
        pl={{ base: 0, md: '12px' }} _before={separator}>
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
    </Grid>
  );
}
