import React, { Suspense } from "react";
import { Box } from "@chakra-ui/react";
import { getQualityTier } from "@/three/quality";
import HeroOrbFallback from "../media/HeroOrbFallback";

// three грузится только на capable-устройствах (lazy → отдельный async-чанк).
const HeroOrb = React.lazy(() => import("../media/HeroOrb"));

/**
 * Герой-визуал: контейнер `.hero-orb` (CSS-halo) + WebGL-блоб или CSS-фолбэк.
 * tier==='off' (reduced-motion / нет WebGL / capture) → three не грузится вовсе.
 */
export default function HeroVisual() {
  const [tier] = React.useState(getQualityTier);
  return (
    <Box className="hero-orb" w="100%" h={{ base: "320px", md: "460px", lg: "540px" }}>
      {tier === "off" ? (
        <HeroOrbFallback />
      ) : (
        <Suspense fallback={<HeroOrbFallback />}>
          <HeroOrb />
        </Suspense>
      )}
    </Box>
  );
}
