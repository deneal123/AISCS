import React from 'react';
import { Box, SimpleGrid, Text, VStack } from '@chakra-ui/react';
import { colors, borderRadius } from '@theme/tokens';
import { GLASS_SURFACE } from '@theme/glass';
import { MERCHANT_REQUISITES } from '@shared/config/merchant';

// Карточка реквизитов ИП — обязательна по требованиям ЮKassa и закона.
// Используется на странице «Контакты» и в текстах оферты/политики.
function RequisitesCard({ compact = false }) {
  return (
    <Box p={compact ? 4 : 6} {...GLASS_SURFACE} borderRadius={borderRadius.lg}>
      <SimpleGrid columns={{ base: 1, sm: 2 }} spacingX={8} spacingY={3}>
        {MERCHANT_REQUISITES.map((item) => (
          <VStack key={item.label} align="flex-start" spacing={0.5}>
            <Text fontSize="11px" textTransform="uppercase" letterSpacing="0.06em" color={colors.text.tertiary}>
              {item.label}
            </Text>
            <Text fontSize="sm" color={colors.text.primary} fontWeight="500">
              {item.value}
            </Text>
          </VStack>
        ))}
      </SimpleGrid>
    </Box>
  );
}

export default RequisitesCard;
