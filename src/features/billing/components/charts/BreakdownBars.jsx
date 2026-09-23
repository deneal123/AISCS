import { useMemo } from 'react';
import { Box, HStack, Text, VStack } from '@chakra-ui/react';
import { FiPieChart } from '@shared/icons';
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { colors, borderRadius } from '@theme/tokens';
import { GLASS_SURFACE } from '@theme/glass';
import { CHAT_THEME } from '../../../chat/constants/theme';
import { agentLabel, formatCredits, pct, rubFromCredits } from '../../lib/credits';

// Инлайн-тултип разбивки трат: ярлык, кредиты, ₽, доля от общего.
function makeTooltip({ rate, total, labelFn }) {
  return function BreakdownTooltip({ active, payload }) {
    if (!active || !payload || !payload.length) return null;
    const row = payload[0].payload || {};
    const rub = rubFromCredits(row.credits, rate);
    return (
      <Box
        px={3}
        py={2}
        minW="170px"
        bg={colors.ink[900]}
        border={`1px solid ${colors.glass.border}`}
        borderRadius={borderRadius.sm}
        boxShadow={colors.glass.highlight}
      >
        <Text fontSize="12px" fontWeight="700" color={CHAT_THEME.textPrimary} mb={1.5} noOfLines={1}>
          {labelFn(row.name)}
        </Text>
        <VStack align="stretch" spacing={1}>
          <HStack justify="space-between" spacing={4}>
            <Text fontSize="12px" color={CHAT_THEME.textSecondary}>Кредиты</Text>
            <Text fontSize="12px" fontWeight="700" color={CHAT_THEME.textPrimary}>{formatCredits(row.credits)}</Text>
          </HStack>
          {rub && (
            <HStack justify="space-between" spacing={4}>
              <Text fontSize="12px" color={CHAT_THEME.textSecondary}>Стоимость</Text>
              <Text fontSize="12px" fontWeight="600" color={colors.accent.subtleText}>{rub}</Text>
            </HStack>
          )}
          <HStack justify="space-between" spacing={4}>
            <Text fontSize="12px" color={CHAT_THEME.textSecondary}>Доля</Text>
            <Text fontSize="12px" color={CHAT_THEME.textPrimary}>{pct(row.credits, total)}%</Text>
          </HStack>
        </VStack>
      </Box>
    );
  };
}

function EmptyState({ title }) {
  return (
    <Box>
      {title && (
        <Text fontSize="12px" color={CHAT_THEME.textSecondary} mb={2}>{title}</Text>
      )}
      <VStack {...GLASS_SURFACE} borderRadius={borderRadius.md} spacing={2.5} py={10} px={4} textAlign="center">
        <Box
          boxSize="40px"
          borderRadius={borderRadius.md}
          bg={CHAT_THEME.accentSoft}
          border={`1px solid ${colors.accent.subtleBorder}`}
          display="flex"
          alignItems="center"
          justifyContent="center"
        >
          <Box as={FiPieChart} color={colors.blue[300]} fontSize="18px" />
        </Box>
        <Text fontSize="12.5px" color={CHAT_THEME.textSecondary} fontWeight="500">
          Нет данных за период
        </Text>
      </VStack>
    </Box>
  );
}

/**
 * Горизонтальные бары разбивки трат (кредиты) с богатым тултипом. По умолчанию
 * подписывает категории как типы операций (agentLabel). Красный не используется.
 */
export default function BreakdownBars({
  data = [],
  title,
  color = colors.blue[500],
  rate,
  labelFn = agentLabel,
}) {
  // Хуки — до раннего return. makeTooltip возвращает НОВЫЙ тип компонента:
  // без мемоизации recharts на каждом рендере ремонтировал тултип с нуля.
  const total = useMemo(
    () => data.reduce((sum, d) => sum + (Number(d.credits) || 0), 0),
    [data],
  );
  const Tip = useMemo(() => makeTooltip({ rate, total, labelFn }), [rate, total, labelFn]);

  if (!data.length) return <EmptyState title={title} />;

  const height = Math.max(160, data.length * 38 + 20);

  return (
    <Box>
      {title && (
        <Text fontSize="12px" color={CHAT_THEME.textSecondary} mb={2}>{title}</Text>
      )}
      <Box h={`${height}px`}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ top: 0, right: 8, left: 4, bottom: 0 }} barCategoryGap="28%">
            <XAxis type="number" tick={{ fontSize: 10, fill: colors.fg[4] }} tickFormatter={formatCredits} />
            <YAxis
              type="category"
              dataKey="name"
              width={132}
              interval={0}
              tickFormatter={labelFn}
              tick={{ fontSize: 10.5, fill: colors.fg[3] }}
            />
            <Tooltip content={<Tip />} cursor={{ fill: colors.border.faint }} />
            <Bar dataKey="credits" fill={color} radius={[0, 4, 4, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </Box>
    </Box>
  );
}
