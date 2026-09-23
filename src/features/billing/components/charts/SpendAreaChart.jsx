import { Box, HStack, Text, VStack } from '@chakra-ui/react';
import { FiBarChart2 } from '@shared/icons';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { colors, borderRadius } from '@theme/tokens';
import { GLASS_SURFACE } from '@theme/glass';
import { CHAT_THEME } from '../../../chat/constants/theme';
import { formatCredits, formatTokens, rubFromCredits } from '../../lib/credits';

function shortDay(iso) {
  if (!iso) return '';
  const parts = String(iso).split('-');
  return parts.length === 3 ? `${parts[2]}.${parts[1]}` : String(iso);
}

// Инлайновый стеклянный тултип: день → кредиты + ₽ + запросы + токены.
function SpendTooltip({ active, payload, rate }) {
  if (!active || !payload || !payload.length) return null;
  const row = payload[0].payload || {};
  const rub = rubFromCredits(row.credits, rate);
  const hasTokens = row.tokens != null;
  return (
    <Box
      px={3}
      py={2}
      minW="150px"
      bg={colors.ink[900]}
      border={`1px solid ${colors.glass.border}`}
      borderRadius={borderRadius.sm}
      boxShadow={colors.glass.highlight}
    >
      <Text fontSize="11px" color={CHAT_THEME.textTertiary} mb={1.5}>
        {shortDay(row.day)}
      </Text>
      <VStack align="stretch" spacing={1}>
        <HStack justify="space-between" spacing={4}>
          <Text fontSize="12px" color={CHAT_THEME.textSecondary}>Кредиты</Text>
          <Text fontSize="12px" fontWeight="700" color={CHAT_THEME.textPrimary}>
            {formatCredits(row.credits)}
          </Text>
        </HStack>
        {rub && (
          <HStack justify="space-between" spacing={4}>
            <Text fontSize="12px" color={CHAT_THEME.textSecondary}>Стоимость</Text>
            <Text fontSize="12px" fontWeight="600" color={colors.accent.subtleText}>{rub}</Text>
          </HStack>
        )}
        <HStack justify="space-between" spacing={4}>
          <Text fontSize="12px" color={CHAT_THEME.textSecondary}>Запросы</Text>
          <Text fontSize="12px" color={CHAT_THEME.textPrimary}>{formatCredits(row.requests)}</Text>
        </HStack>
        {hasTokens && (
          <HStack justify="space-between" spacing={4}>
            <Text fontSize="12px" color={CHAT_THEME.textSecondary}>Токены</Text>
            <Text fontSize="12px" color={CHAT_THEME.textPrimary}>{formatTokens(row.tokens)}</Text>
          </HStack>
        )}
      </VStack>
    </Box>
  );
}

function EmptyState() {
  return (
    <VStack {...GLASS_SURFACE} borderRadius={borderRadius.md} spacing={2.5} py={12} px={4} textAlign="center">
      <Box
        boxSize="44px"
        borderRadius={borderRadius.md}
        bg={CHAT_THEME.accentSoft}
        border={`1px solid ${colors.accent.subtleBorder}`}
        display="flex"
        alignItems="center"
        justifyContent="center"
      >
        <Box as={FiBarChart2} color={colors.blue[300]} fontSize="20px" />
      </Box>
      <Text fontSize="13px" color={CHAT_THEME.textSecondary} fontWeight="500">
        Недостаточно данных для графика
      </Text>
      <Text fontSize="11.5px" color={CHAT_THEME.textTertiary}>
        Начните использовать чат — здесь появится динамика трат.
      </Text>
    </VStack>
  );
}

export default function SpendAreaChart({ series = [], rate, sparkline = false }) {
  if (!series.length) {
    return sparkline ? null : <EmptyState />;
  }
  if (sparkline) {
    return (
      <Box h="56px" mt={1}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={series} margin={{ top: 4, right: 0, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="spendGradSpark" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={colors.iris[500]} stopOpacity={0.45} />
                <stop offset="100%" stopColor={colors.iris[500]} stopOpacity={0} />
              </linearGradient>
            </defs>
            <Area
              type="monotone"
              dataKey="credits"
              stroke={colors.iris[300]}
              strokeWidth={1.5}
              fill="url(#spendGradSpark)"
              isAnimationActive={false}
              dot={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </Box>
    );
  }
  return (
    <Box h="240px">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={series} margin={{ top: 8, right: 8, left: -14, bottom: 0 }}>
          <defs>
            <linearGradient id="spendGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={colors.brand.primary} stopOpacity={0.5} />
              <stop offset="100%" stopColor={colors.brand.primary} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke={colors.surface.tint3} />
          <XAxis dataKey="day" tickFormatter={shortDay} tick={{ fontSize: 10, fill: colors.fg[4] }} />
          <YAxis tick={{ fontSize: 10, fill: colors.fg[4] }} />
          <Tooltip
            content={<SpendTooltip rate={rate} />}
            cursor={{ stroke: colors.glass.borderHi, strokeWidth: 1 }}
          />
          <Area type="monotone" dataKey="credits" stroke={colors.brand.primary} strokeWidth={2} fill="url(#spendGrad)" />
        </AreaChart>
      </ResponsiveContainer>
    </Box>
  );
}
