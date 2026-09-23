import React from "react";
import { Box, Grid, GridItem, HStack, Icon, Text } from "@chakra-ui/react";
import { colors, typography, motion as motionTokens } from "@theme/tokens";
import { Reveal } from "@shared/motion/Reveal";
import { LANDING_WHY } from "@/content/landing";
import { LANDING_ICONS } from "./iconMap";
import SectionHeading from "@shared/marketing/SectionHeading";
import { Section, PageShell } from "@shared/marketing/primitives";

export default function LandingWhy() {
  return (
    <Section id="why" tinted>
      <PageShell>
        <SectionHeading
          eyebrow={LANDING_WHY.eyebrow}
          title={LANDING_WHY.title}
          copy={LANDING_WHY.subtitle}
          align="left"
          size="md"
          index="04"
        />
        {/* Инженерный квадрант — hairline-крест, без карточек */}
        <Grid
          templateColumns={{ base: "1fr", md: "repeat(2, 1fr)" }}
          borderTop={`1px solid ${colors.border.subtle}`}
        >
          {LANDING_WHY.items.map((item, i) => {
            const Ic = LANDING_ICONS[item.icon];
            return (
              <GridItem
                key={item.title}
                borderBottom={`1px solid ${colors.border.subtle}`}
                borderLeft={{ md: i % 2 === 1 ? `1px solid ${colors.border.subtle}` : undefined }}
              >
                <Reveal variant="rise" delay={(i % 2) * 80}>
                  <Box
                    role="group"
                    px={{ base: 0, md: i % 2 === 1 ? 8 : 0 }}
                    pr={{ md: i % 2 === 0 ? 8 : 0 }}
                    py={{ base: 6, md: 9 }}
                  >
                    <HStack spacing={3} mb={2.5} align="center">
                      <Text
                        fontFamily={typography.fontFamily.mono}
                        fontSize="12px"
                        fontWeight="700"
                        color={colors.fg[4]}
                        letterSpacing="0.08em"
                        aria-hidden
                      >
                        {String(i + 1).padStart(2, "0")}
                      </Text>
                      <Box
                        w="34px"
                        h="34px"
                        borderRadius="9px"
                        display="flex"
                        alignItems="center"
                        justifyContent="center"
                        bg={colors.surface.tint2}
                        border={`1px solid ${colors.border.subtle}`}
                        transition={`transform 220ms ${motionTokens.easeOut}, box-shadow 220ms ${motionTokens.easeOut}, border-color 220ms ${motionTokens.easeOut}`}
                        _groupHover={{
                          transform: "translateY(-2px) rotate(-6deg)",
                          borderColor: colors.border.light,
                          boxShadow: `0 0 22px ${colors.accent.glow}`,
                        }}
                      >
                        {Ic && <Icon as={Ic} boxSize="17px" color={colors.blue[300]} aria-hidden />}
                      </Box>
                      <Text as="h3" fontSize={{ base: "18px", md: "21px" }} fontWeight="700" color={colors.fg[1]}>
                        {item.title}
                      </Text>
                    </HStack>
                    <Text fontSize={{ base: "14px", md: "15.5px" }} color={colors.fg[3]} lineHeight="1.65" maxW="520px">
                      {item.description}
                    </Text>
                  </Box>
                </Reveal>
              </GridItem>
            );
          })}
        </Grid>
      </PageShell>
    </Section>
  );
}
