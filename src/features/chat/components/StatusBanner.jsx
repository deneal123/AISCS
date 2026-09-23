import React from 'react';
import { Box, Icon, Text } from '@chakra-ui/react';
import { FiAlertCircle, FiAlertTriangle, FiInfo } from '@shared/icons';
import { colors, borderRadius } from '@theme/tokens';

/**
 * Единый баннер состояния над лентой сообщений (было 3 почти одинаковых блока
 * с литеральными #f87171/#fbbf24/#60a5fa). Статус-цвета — из токенов;
 * красный только для ошибок, амбер — предупреждения, синий — инфо.
 */
const VARIANTS = {
  error: { icon: FiAlertCircle, color: colors.error, bg: colors.errorSoft, border: colors.errorBorder },
  warning: { icon: FiAlertTriangle, color: colors.warning, bg: colors.warningSoft, border: colors.warningBorder },
  info: { icon: FiInfo, color: colors.blue[300], bg: colors.accent.soft, border: colors.accent.subtleBorder },
};

export default function StatusBanner({ status = 'info', children }) {
  const v = VARIANTS[status] || VARIANTS.info;
  // Баннер несёт самые важные сообщения чата (обрыв связи, недоступность
  // провайдера, ошибка) — без live-региона скринридер о них не узнаёт.
  const isError = status === 'error';
  return (
    <Box
      role={isError ? 'alert' : 'status'}
      aria-live={isError ? 'assertive' : 'polite'}
      display="flex"
      alignItems="center"
      gap={2.5}
      px={4}
      py={3}
      mb={4}
      borderRadius={borderRadius.sm}
      bg={v.bg}
      border={`1px solid ${v.border}`}
      backdropFilter="blur(8px)"
    >
      <Icon as={v.icon} color={v.color} boxSize="15px" flexShrink={0} aria-hidden />
      <Text fontSize="13px" color={colors.fg[2]} fontWeight="500" lineHeight="1.45">
        {children}
      </Text>
    </Box>
  );
}
