import { Box, Button, Icon, Text, VStack } from '@chakra-ui/react';
import { FiAlertCircle, FiInbox, FiRefreshCw } from '@shared/icons';
import { colors, borderRadius } from '@theme/tokens';
import { GLASS_SURFACE } from '@theme/glass';

// Тинт панели для hover кнопки «Повторить» (раньше CHAT_THEME.panelHover).
const PANEL_HOVER = colors.glass.hover;

/**
 * Единая заглушка секции: `empty` (пусто) или `error` (не удалось загрузить +
 * кнопка «Повторить»). Стеклянная карточка — чтобы все секции вели себя одинаково.
 *
 * @param {'empty'|'error'} [variant]
 * @param {string} [message]
 * @param {React.ElementType} [icon]
 * @param {() => void} [onRetry]  показывается только при variant="error"
 */
export default function StateCard({ variant = 'empty', message, icon, onRetry }) {
  const isError = variant === 'error';
  const StateIcon = icon || (isError ? FiAlertCircle : FiInbox);
  const accent = isError ? colors.warning : colors.blue[300];
  return (
    <VStack spacing={3} py={10} px={4} textAlign="center" {...GLASS_SURFACE} borderRadius={borderRadius.md}>
      <Box
        boxSize="44px"
        borderRadius={borderRadius.md}
        bg={isError ? colors.warningSoft : colors.accent.subtle}
        border={`1px solid ${isError ? colors.warningBorder : colors.accent.subtleBorder}`}
        display="flex"
        alignItems="center"
        justifyContent="center"
      >
        <Icon as={StateIcon} color={accent} boxSize="20px" />
      </Box>
      <Text fontSize="13px" color={colors.fg[3]} fontWeight="500">
        {message || (isError ? 'Не удалось загрузить данные' : 'Пока пусто')}
      </Text>
      {isError && onRetry && (
        <Button
          size="sm"
          variant="ghost"
          leftIcon={<FiRefreshCw />}
          color={colors.accent.subtleText}
          _hover={{ bg: PANEL_HOVER }}
          onClick={onRetry}
        >
          Повторить
        </Button>
      )}
    </VStack>
  );
}
