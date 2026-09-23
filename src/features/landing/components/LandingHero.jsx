import React from "react";
import { Box, Flex, Grid, GridItem, HStack, Text, VStack } from "@chakra-ui/react";
import { Link as RouterLink } from "react-router-dom";
import MagneticButton from "@shared/controls/MagneticButton";
import { FiArrowRight, FiArrowDownRight } from "@shared/icons";
import { colors, typography } from "@theme/tokens";
import { useAuth } from "@app/providers";
import { Reveal } from "@shared/motion/Reveal";
import { LANDING_HERO } from "@/content/landing";
import HeroVisual from "./HeroVisual";

export default function LandingHero() {
  const { isAuthenticated } = useAuth();
  // Авторизованный тоже может открыть лендинг (/ публичный) — тогда CTA ведёт в чат.
  const primaryCta = isAuthenticated ? { label: "Открыть чат", to: "/chat" } : LANDING_HERO.primaryCta;

  const scrollToExplore = (e) => {
    e.preventDefault();
    document.getElementById(LANDING_HERO.exploreLink.id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <Box position="relative" w="100%" minH={{ base: "auto", md: "calc(100svh - var(--app-header-h))" }} display="flex" alignItems="center" py={{ base: 12, md: 8 }}>
      <Grid
        position="relative"
        zIndex={1}
        w="100%"
        maxW="1520px"
        mx="auto"
        px={{ base: 5, md: 8, lg: 12 }}
        templateColumns={{ base: "1fr", lg: "minmax(0, 0.95fr) minmax(420px, 1.05fr)" }}
        gap={{ base: 8, lg: 12 }}
        alignItems="center"
      >
        <GridItem minW={0}>
          <VStack align={{ base: "center", lg: "flex-start" }} textAlign={{ base: "center", lg: "left" }} spacing={{ base: 6, md: 7 }}>
            {/* Капабилити-пилюля (вместо ряда чипов) */}
            <Reveal variant="soft">
              <Flex
                display="inline-flex"
                align="center"
                flexWrap="wrap"
                gap={2}
                px={4}
                py="7px"
                borderRadius="full"
                border={`1px solid ${colors.glass.borderHi}`}
                bg={colors.glass.bg}
                color={colors.blue[300]}
                fontSize="12px"
                fontWeight={600}
                boxShadow="0 0 24px rgba(94,123,255,0.14), inset 0 1px 0 rgba(255,255,255,0.06)"
                backdropFilter="blur(14px)"
                aria-label="Ключевые возможности"
                // Sheen-луч по пилюле — как в эталоне (у них .hero-pill висит
                // именно здесь, а не на кнопках).
                className="hero-pill"
              >
                <Box as="span" w="6px" h="6px" flexShrink={0} borderRadius="full" bg={colors.blue[500]} animation="pulse-blue 2.8s cubic-bezier(0.4,0,0.6,1) infinite" />
                <Box as="span">LLM-агенты</Box>
                <Box as="span" color={colors.fg[4]} display={{ base: "none", sm: "inline" }}>·</Box>
                <Box as="span" display={{ base: "none", sm: "inline" }}>Веб-поиск · Deep Research</Box>
                <Box as="span" color={colors.fg[4]} display={{ base: "none", md: "inline" }}>·</Box>
                <Box as="span" display={{ base: "none", md: "inline" }}>Память</Box>
              </Flex>
            </Reveal>

            {/* Заголовок — display-scale, 2 строки, иридесцентный акцент */}
            <Reveal variant="rise" delay={120}>
              <Text as="h1" display="grid" gap="4px" m={0} fontSize={{ base: "clamp(34px, 10vw, 46px)", md: "64px", lg: "82px" }} fontWeight="800" lineHeight="1.02" letterSpacing="-0.02em" color="white">
                <Box as="span">{LANDING_HERO.titleLead}</Box>
                <Box as="span" className="iridescent-text">{LANDING_HERO.titleAccent}</Box>
              </Text>
            </Reveal>

            <Reveal variant="soft" delay={240}>
              <VStack align={{ base: "center", lg: "flex-start" }} textAlign={{ base: "center", lg: "left" }} spacing={{ base: 6, md: 7 }}>
                <Text fontSize={{ base: "16px", md: "18px" }} color={colors.fg[3]} maxW="540px" lineHeight="1.65">
                  {LANDING_HERO.subtitle}
                </Text>
                {/* Сбалансированная пара: сплошная primary + контурная/стеклянная
                    secondary. Текст-ссылку «Смотреть возможности» подняли до
                    полноценной вторичной кнопки (плавный скролл к секции). */}
                <HStack spacing={3} flexWrap="wrap" justify={{ base: "center", lg: "flex-start" }}>
                  <MagneticButton as={RouterLink} to={primaryCta.to} variant="primary" size="lg" rightIcon={<FiArrowRight />}>
                    {primaryCta.label}
                  </MagneticButton>
                  <MagneticButton
                    as="a"
                    href={`#${LANDING_HERO.exploreLink.id}`}
                    onClick={scrollToExplore}
                    variant="secondary"
                    size="lg"
                    rightIcon={<FiArrowDownRight />}
                  >
                    {LANDING_HERO.exploreLink.label}
                  </MagneticButton>
                </HStack>
                {/* mono-строка процесса — фирменная деталь */}
                <HStack spacing={2.5} flexWrap="wrap" justify={{ base: "center", lg: "flex-start" }} fontSize="12px" fontFamily={typography.fontFamily.mono} color={colors.fg[4]}>
                  <Box as="span">Запрос → оркестратор → нужный агент → результат</Box>
                  <Box as="span" w="4px" h="4px" borderRadius="full" bg={colors.border.strong} />
                  <Box as="span">{LANDING_HERO.note}</Box>
                </HStack>
              </VStack>
            </Reveal>
          </VStack>
        </GridItem>
        <GridItem display={{ base: "none", md: "block" }} minW={0}>
          <HeroVisual />
        </GridItem>
      </Grid>
    </Box>
  );
}
