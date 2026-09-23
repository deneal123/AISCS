import React from "react";
import { Box, HStack, Icon, Text, VStack } from "@chakra-ui/react";
import { Global } from "@emotion/react";
import { FiCpu, FiGlobe, FiMessageSquare, FiShield } from "@shared/icons";
import { colors, gradients, typography } from "@theme/tokens";
import { Reveal } from "@shared/motion/Reveal";
import Eyebrow from "@shared/brand/Eyebrow";
import { AUTH_FONT_FAMILY } from "../constants";
import { AUTH_SHOWCASE } from "@/content/auth";

// Иконки по имени из content/auth.js (фичи не могут тянуть чужой feature-модуль).
const SHOWCASE_ICONS = { FiMessageSquare, FiGlobe, FiShield, FiCpu };

function AuthBrandPanel() {
  return (
    <VStack
      display={{ base: "none", lg: "flex" }}
      align="flex-start"
      spacing={8}
      w="400px"
      flexShrink={0}
      mr={16}
      position="relative"
      // Мягкий тёмный ореол за текстом — читаемость поверх орба и линий фона.
      sx={{
        "&::before": {
          content: '""',
          position: "absolute",
          inset: "-32px -56px",
          background:
            "radial-gradient(ellipse 78% 92% at 32% 46%, rgba(4,6,14,0.82) 0%, rgba(4,6,14,0.5) 46%, transparent 76%)",
          filter: "blur(10px)",
          zIndex: -1,
          pointerEvents: "none",
        },
      }}
    >
      <Reveal variant="deep" style={{ width: "100%" }}>
        <VStack align="flex-start" spacing={4}>
          <Box className="section-header-eyebrow">
            <Eyebrow>{AUTH_SHOWCASE.eyebrow}</Eyebrow>
          </Box>
          <Text
            as="h2"
            className="section-header-title"
            fontSize={{ base: "30px", md: "38px" }}
            fontWeight="800"
            color="white"
            lineHeight="1.12"
            letterSpacing="-0.03em"
            textShadow="0 2px 16px rgba(0,0,0,0.7)"
          >
            {AUTH_SHOWCASE.title}
          </Text>
        </VStack>
      </Reveal>
      <VStack className="stagger-children" align="stretch" spacing={0} as={Reveal} w="100%">
        {AUTH_SHOWCASE.highlights.map(({ icon, title, description }, i) => {
          const IconCmp = SHOWCASE_ICONS[icon];
          return (
            <HStack
              key={title}
              align="flex-start"
              spacing={3.5}
              py={4}
              borderTop={i === 0 ? undefined : `1px solid ${colors.border.subtle}`}
            >
              <Text
                fontFamily={typography.fontFamily.mono}
                fontSize="11px"
                fontWeight="700"
                color={colors.blue[300]}
                letterSpacing="0.08em"
                pt="3px"
                textShadow="0 1px 8px rgba(0,0,0,0.7)"
                aria-hidden
              >
                {String(i + 1).padStart(2, "0")}
              </Text>
              <Box
                boxSize="36px"
                flexShrink={0}
                borderRadius="10px"
                bg={colors.accent.soft}
                border={`1px solid ${colors.accent.subtleBorder}`}
                display="flex"
                alignItems="center"
                justifyContent="center"
              >
                {IconCmp && <Icon as={IconCmp} boxSize="16px" color={colors.blue[300]} />}
              </Box>
              <VStack align="flex-start" spacing={0.5}>
                <Text fontSize="15px" fontWeight="600" color="white" textShadow="0 1px 10px rgba(0,0,0,0.7)">
                  {title}
                </Text>
                <Text fontSize="13px" color="rgba(214, 221, 240, 0.92)" lineHeight="1.5" maxW="300px" textShadow="0 1px 8px rgba(0,0,0,0.65)">
                  {description}
                </Text>
              </VStack>
            </HStack>
          );
        })}
      </VStack>
    </VStack>
  );
}

function AuthPageShell({ children, topGradient, bottomGradient, containerProps = {} }) {
  return (
    <>
      <Global
        styles={{
          "html, body": {
            scrollbarColor: `rgba(45, 91, 255, 0.62) ${colors.border.subtle}`,
            scrollbarWidth: "thin",
          },
          "html::-webkit-scrollbar, body::-webkit-scrollbar": { width: "10px" },
          "html::-webkit-scrollbar-track, body::-webkit-scrollbar-track": { background: colors.border.subtle },
          "html::-webkit-scrollbar-thumb, body::-webkit-scrollbar-thumb": {
            background: "linear-gradient(180deg, rgba(45, 91, 255, 0.72) 0%, rgba(30, 71, 230, 0.9) 100%)",
            borderRadius: "999px",
            border: "2px solid rgba(6, 6, 6, 0.9)",
          },
        }}
      />

      <Box
        position="relative"
        flex="1"
        w="100%"
        display="flex"
        alignItems="center"
        justifyContent="center"
        fontFamily={AUTH_FONT_FAMILY}
        py={{ base: 12, md: 16 }}
        {...containerProps}
      >
        {/* Приглушённая амбиентная глубина: основной фон дают «рёбра» (AuthLayout),
            здесь — лёгкий mesh + сетка + иридесцентный орб за витриной. */}
        <Box position="absolute" inset={0} pointerEvents="none" zIndex={0} overflow="hidden">
          <Box position="absolute" inset={0} bgImage={gradients.midnightMesh} opacity={0.28} />
          <Box
            position="absolute"
            top="-12%"
            left="50%"
            w="min(900px, 90vw)"
            h="70%"
            transform="translateX(-50%)"
            bgImage={gradients.glow}
            opacity={0.3}
            filter="blur(28px)"
          />
          {topGradient && <Box position="absolute" filter="blur(60px)" {...topGradient} />}
          {bottomGradient && <Box position="absolute" filter="blur(60px)" {...bottomGradient} />}
          <Box
            position="absolute"
            inset={0}
            backgroundImage="linear-gradient(rgba(140,160,255,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(140,160,255,0.04) 1px, transparent 1px)"
            backgroundSize="44px 44px"
            opacity={0.35}
            sx={{ maskImage: "radial-gradient(70% 60% at 50% 40%, #000 0%, transparent 80%)" }}
          />
          {/* Иридесцентный орб за витриной (desktop) — чистый CSS, без второго
              WebGL-контекста; на мобиле витрина скрыта, орб не нужен. */}
          <Box
            display={{ base: "none", lg: "block" }}
            position="absolute"
            top="50%"
            left="26%"
            w="440px"
            h="440px"
            transform="translate(-50%, -50%)"
            opacity={0.32}
            aria-hidden
          >
            <div className="hero-orb-fallback">
              <span className="hero-orb-fallback-sheen" />
            </div>
          </Box>
        </Box>
        <HStack position="relative" zIndex={1} spacing={0} justify="center" align="center" w="100%" px={{ base: 4, lg: 8 }}>
          <AuthBrandPanel />
          <Reveal variant="soft" style={{ width: "100%", maxWidth: "460px" }}>
            {children}
          </Reveal>
        </HStack>
      </Box>
    </>
  );
}

export default AuthPageShell;
