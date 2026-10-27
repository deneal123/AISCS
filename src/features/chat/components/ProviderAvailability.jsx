import React, { useEffect } from 'react';
import {
  Box, Button, HStack, Popover, PopoverBody, PopoverCloseButton,
  PopoverContent, PopoverHeader, PopoverTrigger, Portal, Text, VStack, useDisclosure,
} from '@chakra-ui/react';
import { useResponsive } from '@hooks/useResponsive';
import { borderRadius, colors, layers } from '@theme/tokens';
import { useProviderStatus } from '../hooks/useProviderStatus';
import ChoicePanel from '@shared/controls/ChoicePanel';

const META = {
  available: { color: colors.success, label: 'ИИ доступен' },
  degraded: { color: colors.warning, label: 'ИИ доступен частично' },
  unavailable: { color: colors.error, label: 'ИИ временно недоступен' },
  unknown: { color: colors.fg[3], label: 'Доступность ИИ неизвестна' },
};
const ROW_LABELS = {
  ready: 'Доступен', unavailable: 'Недоступен', disabled: 'Выключен',
  unknown: 'Нет проверки', stale: 'Данные устарели',
};

function ProviderSignalIcon(props) {
  return <svg viewBox="0 0 24 24" {...props}>
    <rect x="3" y="14" width="4" height="7" rx="1" fill="currentColor" />
    <rect x="10" y="8" width="4" height="13" rx="1" fill="currentColor" />
    <rect x="17" y="2" width="4" height="19" rx="1" fill="currentColor" />
  </svg>;
}

export default function ProviderAvailability({ compact = false }) {
  const { data, stale } = useProviderStatus();
  const { isMobile } = useResponsive();
  const { isOpen, onOpen, onClose, onToggle } = useDisclosure();
  useEffect(() => {
    if (!isOpen) return undefined;
    // Hover opens without moving focus from the editor. Escape still dismisses
    // this overlay first rather than reaching the composer/run shortcuts.
    const dismiss = (event) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      event.stopPropagation();
      onClose();
    };
    document.addEventListener('keydown', dismiss, true);
    return () => document.removeEventListener('keydown', dismiss, true);
  }, [isOpen, onClose]);
  const validCounts = Number.isInteger(data?.ready) && Number.isInteger(data?.total)
    && data.ready >= 0 && data.ready <= data.total && data.total <= 32;
  const state = !stale && validCounts && Object.hasOwn(META, data?.state) ? data.state : 'unknown';
  const meta = META[state];
  const rows = Array.isArray(data?.providers) ? data.providers.slice(0, 32) : [];
  const label = stale ? 'Доступность ИИ: нет свежих данных' : meta.label;
  const details = <>
            <Text fontSize="12px" color={meta.color} mb={3}>{label}</Text>
            {validCounts && rows.length > 0 && <Text fontSize="11px" color={colors.fg[2]} mb={3}>
              {stale ? 'При последней проверке' : 'Доступно провайдеров'}: {data.ready} из {data.total}
            </Text>}
            <VStack as="ul" listStyleType="none" m={0} p={0} spacing={3} align="stretch">
              {rows.map((row) => (
                <HStack as="li" key={row.id} spacing={3} justify="space-between">
                  <Box minW={0}>
                    <Text fontSize="12px" overflowWrap="anywhere">{row.label}</Text>
                    {row.primary && <Text fontSize="10px" color={colors.fg[3]}>Основной</Text>}
                  </Box>
                  <HStack spacing={2} flexShrink={0}>
                    <Box aria-hidden="true" boxSize="5px" borderRadius="full"
                      bg={stale ? colors.fg[3] : row.state === 'ready' ? colors.success
                        : row.state === 'unavailable' ? colors.error : colors.fg[3]} />
                    <Text fontSize="11px" color={colors.fg[2]}>
                      {stale ? 'Данные устарели' : ROW_LABELS[row.state] || 'Нет проверки'}
                    </Text>
                  </HStack>
                </HStack>
              ))}
            </VStack>
            {!rows.length && <Text fontSize="12px" color={colors.fg[3]}>Статусы пока недоступны.</Text>}
            <Text mt={3} fontSize="10px" color={colors.fg[3]}>
              Фоновая проверка · без платных запросов.
              Доступность отдельных моделей может отличаться.
            </Text>
  </>;
  if (isMobile) return <ChoicePanel label={label} title="Доступность ИИ"
    icon={ProviderSignalIcon} iconColor={meta.color} mobileIconOnly
    triggerTestId="provider-availability" variant="status-palette" mobileWidth={280}>
    {() => details}
  </ChoicePanel>;
  return (
    <Popover trigger={isMobile ? 'click' : 'hover'} placement={compact ? 'top-end' : 'bottom-end'} isLazy
      isOpen={isOpen} onOpen={onOpen} onClose={onClose}
      openDelay={200} closeDelay={150} autoFocus={false} returnFocusOnClose={isMobile}>
      <PopoverTrigger>
        <Button aria-label={label} data-testid="provider-availability" variant="ghost"
          onClick={(event) => { event.preventDefault(); if (isMobile) onToggle(); else onOpen(); }}
          onFocus={() => { if (!isMobile) onOpen(); }}
          size="xs" h={compact ? '44px' : '30px'} w={compact ? '44px' : '48px'} minW={compact ? '44px' : '48px'} px={compact ? 0 : '6px'} flexShrink={0}
          borderRadius={borderRadius.control} color={meta.color}
          _hover={{ bg: colors.ink[800] }} _active={{ bg: colors.ink[800] }}
          _focusVisible={{ boxShadow: `0 0 0 2px ${colors.blue[500]}` }}>
          <HStack spacing="2px" h={compact ? '30px' : '14px'} w={compact ? '30px' : undefined}
            border={compact ? `1px solid ${colors.glass.border}` : undefined}
            borderRadius={compact ? 'full' : undefined}
            justify={compact ? 'center' : undefined} pb={compact ? '8px' : 0}
            align="flex-end" aria-hidden="true">
            {[5, 9, 13].map((height) => <Box key={height} w="3px" h={`${height}px`}
              borderRadius="1px" bg="currentColor" />)}
          </HStack>
          {!compact && <Text as="span" ml="6px" fontSize="11px" color={colors.fg[2]}>ИИ</Text>}
        </Button>
      </PopoverTrigger>
      {isOpen && <Portal>
        <PopoverContent motionProps={{ animate: false }} style={{ visibility: 'visible', opacity: 1, transform: 'none' }}
          bg={colors.bg.menu} color={colors.fg[1]} borderColor={colors.border.medium}
          borderRadius={borderRadius.sm} w="284px" maxW="calc(100vw - 24px)"
          maxH="calc(var(--app-visual-height, 100dvh) - 64px)" zIndex={layers.popover} overflowY="auto">
          <PopoverHeader border={0} fontSize="13px" fontWeight={600} pr={10} pb={1}>
            Доступность ИИ
          </PopoverHeader>
          {isMobile && <PopoverCloseButton aria-label="Закрыть статусы провайдеров" boxSize="44px" />}
          <PopoverBody pt={1} px={4} pb={4}>
            {details}
          </PopoverBody>
        </PopoverContent>
      </Portal>}
    </Popover>
  );
}
