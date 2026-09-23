import { Box, HStack, Icon, Text, Tooltip } from '@chakra-ui/react';
import { FiInfo } from '@shared/icons';
import { colors, borderRadius } from '@theme/tokens';
import { GLASS_SURFACE, CARD_HOVER_SOFT, CARD_TRANSITION } from '@theme/glass';
import { CHAT_THEME } from '../../chat/constants/theme';
import { MICRO_LABEL_SX } from '@theme/styles';

/**
 * Плитка метрики: лейбл + значение, опц. подзначение (₽), подсказка (Chakra
 * Tooltip), тренд и акцент-цвет иконки. Мягкий hover (CARD_HOVER_SOFT).
 * NB: не путать с shared/ui/atoms/StatCard — это отдельная биллинговая плитка.
 */
export default function StatCard({
  label,
  value,
  subValue,
  hint,
  trend,
  icon: StatIcon,
  accent = colors.blue[300],
}) {
  return (
    <Box
      p={4}
      {...GLASS_SURFACE}
      borderRadius={borderRadius.md}
      transition={CARD_TRANSITION}
      _hover={CARD_HOVER_SOFT}
    >
      <HStack justify="space-between" align="center" mb={1.5}>
        <HStack spacing={2} minW={0}>
          {StatIcon && <Icon as={StatIcon} boxSize={3.5} color={accent} flexShrink={0} />}
          <Text {...MICRO_LABEL_SX} noOfLines={1}>
            {label}
          </Text>
        </HStack>
        {hint && (
          <Tooltip label={hint} placement="top" hasArrow openDelay={200} fontSize="11px">
            <Box as="span" display="inline-flex" color={CHAT_THEME.textTertiary} cursor="help">
              <Icon as={FiInfo} boxSize={3} />
            </Box>
          </Tooltip>
        )}
      </HStack>
      <Text fontSize="20px" fontWeight="700" color={CHAT_THEME.textPrimary} lineHeight="1.1" noOfLines={1}>
        {value}
      </Text>
      {(subValue || trend) && (
        <HStack spacing={2} mt={1} align="baseline">
          {subValue && (
            <Text fontSize="11.5px" color={colors.accent.subtleText} fontWeight="600">
              {subValue}
            </Text>
          )}
          {trend && (
            <Text fontSize="11px" color={trend.color || CHAT_THEME.textTertiary}>
              {trend.label}
            </Text>
          )}
        </HStack>
      )}
    </Box>
  );
}
