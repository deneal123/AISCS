import { Box } from '@chakra-ui/react';
import { colors, typography } from '@theme/tokens';
import { modelLabel } from '../lib/credits';

/**
 * Компактный чип модели (mono, iris-тинт) — общий для «Самых дорогих запросов»
 * и строк истории списаний. Синий-акцент только как subtle-заливка (не solid).
 */
export default function ModelChip({ model, ...rest }) {
  if (!model) return null;
  return (
    <Box
      as="span"
      flexShrink={0}
      fontSize="10px"
      fontWeight="700"
      letterSpacing="0.02em"
      px={1.5}
      py="1px"
      borderRadius="full"
      color={colors.blue[300]}
      bg={colors.accent.subtle}
      border={`1px solid ${colors.accent.subtleBorder}`}
      fontFamily={typography.fontFamily.mono}
      title={String(model)}
      {...rest}
    >
      {modelLabel(model)}
    </Box>
  );
}
