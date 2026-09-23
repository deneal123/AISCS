import React from "react";
import { Box, Flex, Text } from "@chakra-ui/react";
import { Link as RouterLink } from "react-router-dom";
import MagneticButton from "@shared/controls/MagneticButton";
import { borderRadius, colors, gradients, shadows } from "@theme/tokens";
import { GLASS_CARD_BASE, CARD_TRANSITION } from "@theme/glass";
import { Reveal } from "@shared/motion/Reveal";
import { useInView } from "@hooks/useInView";

/**
 * CTA-band — стеклянная полоса призыва по композиции эталона (PageCTA):
 * ГОРИЗОНТАЛЬНАЯ (текст слева, кнопки справа), а не центрированная стопка —
 * так финал не читается как шаблонный «лендинговый» блок. Диагональная
 * синяя→cyan заливка, бесконечный скан-луч (.cta-scan), магнитная primary.
 * Секцию-обёртку (paddings/id) задаёт вызывающий.
 */
export default function CtaBand({ title, subtitle, primaryCta, secondaryCta }) {
  // Грань — самая дорогая анимация в проекте, а полоса живёт в самом низу
  // лендинга: без гейта она крутилась с момента загрузки, за пять экранов от
  // вьюпорта, и не останавливалась никогда. once=false — гасим и при уходе.
  const [ref, inView] = useInView(0.2, "0px", false);
  return (
    <Reveal variant="rise">
      {/* Обёртка нужна из-за псевдоэлементов: сама полоса уже занимает и
          `_before` (заливка), и `_after` (скан-луч), поэтому золотую грань
          вешаем на внешний Box — у него ::before свободен. */}
      <Box ref={ref} className={inView ? "gold-edge" : undefined} borderRadius={borderRadius.lg}>
      <Flex
        {...GLASS_CARD_BASE}
        transition={CARD_TRANSITION}
        direction={{ base: "column", md: "row" }}
        align={{ base: "stretch", md: "center" }}
        gap={{ base: 6, md: 8 }}
        minH="174px"
        px={{ base: 6, md: 11 }}
        py={{ base: 7, md: 10 }}
        _hover={{
          transform: "translateY(-2px)",
          borderColor: colors.glass.borderHi,
          boxShadow: shadows.glassLift,
        }}
        _before={{
          content: '""',
          position: "absolute",
          inset: 0,
          background: gradients.ctaWash,
          pointerEvents: "none",
        }}
        _after={{
          content: '""',
          position: "absolute",
          inset: 0,
          background: gradients.ctaScan,
          transform: "translateX(-120%)",
          animation: "cta-scan 7.5s ease-in-out infinite",
          pointerEvents: "none",
        }}
      >
        <Box position="relative" zIndex={1} flex="1" minW={0}>
          <Text as="h2" fontSize={{ base: "24px", md: "30px" }} fontWeight="800" lineHeight="1.12" color={colors.fg[1]}>
            {title}
          </Text>
          <Text mt={3} fontSize={{ base: "14.5px", md: "15px" }} color={colors.fg[3]} lineHeight="1.55" maxW="650px">
            {subtitle}
          </Text>
        </Box>
        <Flex position="relative" zIndex={1} wrap="wrap" gap={2.5} flexShrink={0}>
          <MagneticButton as={RouterLink} to={primaryCta.to} variant="primary" size="lg">
            {primaryCta.label}
          </MagneticButton>
          {secondaryCta && (
            <MagneticButton as={RouterLink} to={secondaryCta.to} variant="secondary" size="lg">
              {secondaryCta.label}
            </MagneticButton>
          )}
        </Flex>
      </Flex>
      </Box>
    </Reveal>
  );
}
