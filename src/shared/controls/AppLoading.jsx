import React from 'react';
import { Center, Spinner, Text, VStack } from '@chakra-ui/react';
import { colors } from '@theme/tokens';

/** Shared indeterminate feedback; the parent retains scroll/layout ownership. */
export default function AppLoading({ label = 'Загружаю страницу…' }) {
  return (
    <Center flex="1" minH={0} w="full" py={6} role="status" aria-live="polite" aria-atomic="true">
      <VStack spacing={3}>
        <Spinner aria-hidden="true" color={colors.blue[300]}
          sx={{ '@media (prefers-reduced-motion: reduce)': { animation: 'none' } }} />
        <Text fontSize="sm" color={colors.fg[3]}>{label}</Text>
      </VStack>
    </Center>
  );
}
