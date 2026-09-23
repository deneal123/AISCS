import React from "react";
import { Box, keyframes } from "@chakra-ui/react";
import { Outlet, useLocation } from "react-router-dom";
import Header from "./Header";
import SkipLink from "./SkipLink";
import Footer from "./Footer";
import { colors, gradients, spacing } from "@theme/tokens";
import { ScrollToTop } from "@shared/ui/atoms";
import { isChatRoute, isLandingRoute, isPlatformRoute, shouldUseFullWidthLayout } from "@app/router";
import FinsBackground from "@shared/visual/FinsBackground";
import MobileStickyCTA from "@features/landing/components/MobileStickyCTA";

// CSS animation for page transitions - works on iOS Safari
const fadeIn = keyframes`
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
`;

function PublicLayout() {
  const location = useLocation();
  const isWorkspacePage = isChatRoute(location.pathname);
  const isFullWidthPage = shouldUseFullWidthLayout(location.pathname);
  const isLanding = isLandingRoute(location.pathname);
  // /platform получает ту же анимированную глубину, что и лендинг («рёбра» + лёгкий mesh).
  const isAmbient = isLanding || isPlatformRoute(location.pathname);

  return (
    <Box position="relative" bg={colors.background.darkPrimary} w="100%" minH="100vh" display="flex" flexDirection="column">
      <SkipLink />
      <ScrollToTop />

      {/* Лендинг и /platform: фон-«рёбра» на всю страницу (fixed, вне трансформированного main). */}
      {isAmbient && <FinsBackground />}

      {/* Амбиентная глубина (InCellCorp): синий mesh + hero-glow. pointer-events:none критично.
          На лендинге/платформе приглушаем — там основной фон дают «рёбра». */}
      <Box
        aria-hidden
        position="fixed"
        inset={0}
        bgImage={gradients.midnightMesh}
        opacity={isAmbient ? 0.25 : 0.55}
        pointerEvents="none"
        zIndex={0}
        sx={{ maskImage: "radial-gradient(120% 90% at 50% 0%, #000 55%, transparent 100%)" }}
      />
      {!isAmbient && (
        <Box
          aria-hidden
          position="fixed"
          top={0}
          left={0}
          right={0}
          h="62vh"
          bgImage={gradients.bloomHero}
          opacity={0.6}
          pointerEvents="none"
          zIndex={0}
        />
      )}
      {/* Тёмная вуаль ко дну вьюпорта — ТОЛЬКО там, где нет «рёбер». На лендинге
          и /platform она накрывала фон (к низу до 85% черноты) и, будучи fixed,
          съедала линии при любом скролле — отсюда «линии иногда вообще не видно».
          У эталона над WebGL-фоном такой вуали нет вовсе: читаемость обеспечивают
          виньетка в самом шейдере и приглушённая интенсивность. */}
      {!isAmbient && (
        <Box
          aria-hidden
          position="fixed"
          inset={0}
          bg="linear-gradient(180deg, transparent 0%, rgba(3,4,9,0.35) 55%, rgba(3,4,9,0.85) 100%)"
          pointerEvents="none"
          zIndex={0}
        />
      )}

      {!isWorkspacePage && (
        <Box position="sticky" top={0} zIndex={100}>
          <Header />
        </Box>
      )}

      {/* Main content - uses CSS animation instead of framer-motion.
          minH="100svh" держит контент минимум на фолд, чтобы футер уходил ПОД
          него (виден только прокруткой) — претензия #4. */}
      <Box
        as="main"
        id="main"
        position="relative"
        zIndex={1}
        key={location.pathname}
        flex="1 0 auto"
        minH="100svh"
        display="flex"
        flexDirection="column"
        animation={`${fadeIn} 0.3s ease-out forwards`}
        sx={{ "@media (prefers-reduced-motion: reduce)": { animation: "none" } }}
      >
        {isFullWidthPage ? (
          <Outlet />
        ) : (
          <Box
            maxW="6xl"
            mx="auto"
            py={{ base: 10, md: 14 }}
            px={{ base: spacing.md, md: spacing.lg, lg: spacing[13] }}
          >
            <Outlet />
          </Box>
        )}
      </Box>

      {!isWorkspacePage && (
        <Box position="relative" zIndex={1}>
          <Footer />
        </Box>
      )}

      {isLanding && <MobileStickyCTA />}
    </Box>
  );
}

export default PublicLayout;
