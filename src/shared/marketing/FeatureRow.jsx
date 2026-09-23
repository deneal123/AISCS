import React from "react";
import { Box, Grid, GridItem, HStack, Icon, Text } from "@chakra-ui/react";
import { colors, typography } from "@theme/tokens";
import { Reveal } from "@shared/motion/Reveal";

/**
 * Плотный редакторский hairline-список (замена сетке одинаковых стеклянных карт).
 *
 * Ряды разделены тонкими линиями, без заливки/карточек — воздух + структура.
 * Слева mono-индекс + иконка, справа заголовок/описание. На hover — акцент
 * индекса и лёгкий сдвиг (сдержанно). Двухколоночная плотная раскладка на md+.
 *
 * items: [{ icon: Component, title, description }]
 * columns: число колонок на md+ (default 2)
 */
export default function FeatureRow({ items, columns = 2 }) {
  return (
    <Grid
      role="list"
      templateColumns={{ base: "1fr", md: `repeat(${columns}, 1fr)` }}
      columnGap={{ md: 12, lg: 16 }}
      borderTop={`1px solid ${colors.border.subtle}`}
    >
      {items.map((item, i) => (
        <GridItem key={item.title} role="listitem">
          <Reveal variant="rise" delay={(i % columns) * 70}>
            <Box
              role="group"
              py={{ base: 5, md: 7 }}
              borderBottom={`1px solid ${colors.border.subtle}`}
              transition="border-color 200ms"
              _hover={{ borderBottomColor: colors.border.light }}
            >
              <HStack align="flex-start" spacing={4}>
                <Text
                  fontFamily={typography.fontFamily.mono}
                  fontSize="12px"
                  fontWeight="700"
                  color={colors.fg[4]}
                  letterSpacing="0.08em"
                  pt="3px"
                  transition="color 200ms"
                  _groupHover={{ color: colors.blue[300] }}
                  aria-hidden
                >
                  {String(i + 1).padStart(2, "0")}
                </Text>
                <Box flex="1">
                  <HStack spacing={2.5} mb={1.5}>
                    {item.icon && (
                      <Icon as={item.icon} boxSize="18px" color={colors.blue[300]} aria-hidden />
                    )}
                    <Text as="h3" fontSize={{ base: "17px", md: "19px" }} fontWeight="700" color={colors.fg[1]}>
                      {item.title}
                    </Text>
                  </HStack>
                  <Text fontSize={{ base: "14px", md: "15px" }} color={colors.fg[3]} lineHeight="1.6">
                    {item.description}
                  </Text>
                </Box>
              </HStack>
            </Box>
          </Reveal>
        </GridItem>
      ))}
    </Grid>
  );
}
