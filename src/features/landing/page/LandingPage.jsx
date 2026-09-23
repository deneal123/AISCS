import React from "react";
import { Box } from "@chakra-ui/react";
import LandingHero from "../components/LandingHero";
import LandingFeatures from "../components/LandingFeatures";
import LandingUseCases from "../components/LandingUseCases";
import LandingHow from "../components/LandingHow";
import LandingWhy from "../components/LandingWhy";
import LandingMetrics from "../components/LandingMetrics";
import LandingTrust from "../components/LandingTrust";
import LandingFaq from "../components/LandingFaq";
import LandingCTA from "../components/LandingCTA";

/**
 * Лендинг GPTHub — полный маркетинговый лендинг. Фон-«рёбра» на всю страницу
 * монтируется в PublicLayout (fixed, вне трансформированного main).
 * Порядок: герой → фичи → сценарии → как работает → почему → метрики →
 * доверие → FAQ → CTA. Общий Header (с якорями) + Footer + MobileStickyCTA.
 */
export default function LandingPage() {
  return (
    // overflow-x hidden клипает горизонтальный вылет декоративных орбов.
    <Box position="relative" zIndex={1} w="100%" overflowX="hidden">
      <LandingHero />
      <LandingFeatures />
      <LandingUseCases />
      <LandingHow />
      <LandingWhy />
      <LandingMetrics />
      <LandingTrust />
      <LandingFaq />
      <LandingCTA />
    </Box>
  );
}
