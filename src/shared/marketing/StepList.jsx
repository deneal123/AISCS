import React from "react";
import { Box, Grid, GridItem, Text } from "@chakra-ui/react";
import { colors, typography } from "@theme/tokens";
import { Reveal } from "@shared/motion/Reveal";

/**
 * Редакторский нумерованный список (замена ряду стеклянных «шагов»).
 *
 * Левый rail с крупными mono-нумералами и вертикальной градиент-линией
 * (фирменный «живой» акцент GPThub) + правая колонка заголовок/описание,
 * разделённые hairline. Без карточек — воздух и разделители, не стекло.
 *
 * steps: [{ n, title, description }]
 */
export default function StepList({ steps }) {
  return (
    <Box position="relative" role="list">
      {steps.map((step, i) => (
        <Reveal key={step.n} variant="rise" delay={i * 90}>
          <Grid
            templateColumns={{ base: "48px 1fr", md: "132px 1fr" }}
            gap={{ base: 4, md: 8 }}
            py={{ base: 6, md: 8 }}
            borderTop={i === 0 ? undefined : `1px solid ${colors.border.faint}`}
            role="listitem"
          >
            {/* Rail: нумерал + соединительная линия */}
            <GridItem position="relative">
              <Text
                fontFamily={typography.fontFamily.mono}
                fontWeight="700"
                lineHeight="1"
                fontSize={{ base: "34px", md: "64px" }}
                letterSpacing="-0.02em"
                className="iridescent-text"
                aria-hidden
              >
                {step.n}
              </Text>
              {i < steps.length - 1 && (
                <Box
                  aria-hidden
                  position="absolute"
                  left={{ base: "9px", md: "13px" }}
                  top={{ base: "44px", md: "78px" }}
                  bottom={{ base: "-48px", md: "-64px" }}
                  w="1px"
                  bgGradient={`linear(to-b, ${colors.blue[500]}, ${colors.iris[500]}, transparent)`}
                  opacity={0.5}
                />
              )}
            </GridItem>

            <GridItem>
              <Text
                as="h3"
                fontSize={{ base: "19px", md: "24px" }}
                fontWeight="700"
                color={colors.fg[1]}
               
                mb={2}
              >
                {step.title}
              </Text>
              <Text
                fontSize={{ base: "14px", md: "16px" }}
                color={colors.fg[3]}
                lineHeight="1.65"
                maxW="640px"
              >
                {step.description}
              </Text>
            </GridItem>
          </Grid>
        </Reveal>
      ))}
    </Box>
  );
}
