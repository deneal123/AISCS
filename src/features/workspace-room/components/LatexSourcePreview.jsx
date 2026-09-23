import { useMemo } from 'react';
import { Box, Text } from '@chakra-ui/react';
import { colors, typography } from '@theme/tokens';
import { WORK_SCROLLBAR_SX } from '../model/theme';

const TOKEN = /(\\[A-Za-z@]+\*?|%[^\n]*|\$\$?|[[\]{}&_^#])/g;
const IS_TOKEN = /^(?:\\[A-Za-z@]+\*?|%[^\n]*|\$\$?|[[\]{}&_^#])$/;

const tokenColor = (token) => {
  if (token.startsWith('%')) return colors.fg[4];
  if (token.startsWith('\\')) return colors.blue[300];
  if (token.startsWith('$')) return colors.success;
  return colors.iris[200];
};

export function LatexSourcePreview({ value, label }) {
  const tokens = useMemo(
    () => String(value || '').split(TOKEN).filter((token) => token !== ''),
    [value],
  );
  return (
    <Box
      flex="1"
      minH={0}
      overflow="auto"
      aria-label={label}
      role="region"
      sx={WORK_SCROLLBAR_SX}
    >
      <Text
        as="pre"
        minH="100%"
        m={0}
        p={4}
        whiteSpace="pre-wrap"
        overflowWrap="anywhere"
        fontFamily={typography.fontFamily.mono}
        fontSize="12px"
        color={colors.fg[2]}
      >
        {tokens.map((token, index) => (
          <Box as="span" color={IS_TOKEN.test(token) ? tokenColor(token) : 'inherit'} key={index}>
            {token}
          </Box>
        ))}
      </Text>
    </Box>
  );
}
