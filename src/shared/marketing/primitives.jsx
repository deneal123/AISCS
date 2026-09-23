import React from "react";
import { Box, Grid } from "@chakra-ui/react";
import { colors, gradients } from "@theme/tokens";

/**
 * Примитивы раскладки маркетинга — единый источник шелла и вертикального ритма
 * (раньше каждая секция хардкодила maxW/px/py, из-за чего ритм не модулировался).
 */

/** Шелл контента: общий 1520 + флюидные поля. */
export function PageShell({ children, ...rest }) {
  return (
    <Box w="100%" maxW="1520px" mx="auto" px="clamp(20px, 4vw, 56px)" {...rest}>
      {children}
    </Box>
  );
}

/**
 * Секция с системным ритмом вместо хардкода py:
 * `compact` — плотный шаг (модуляция ритма), `tinted` — тонированная панель
 * (перебой), `orb` — фирменный section-orb GPThub ("blue" | "violet").
 */
export function Section({
  children,
  id,
  tinted = false,
  compact = false,
  orb,
  as = "section",
  overflow,
  ...rest
}) {
  return (
    <Box
      as={as}
      id={id}
      position="relative"
      zIndex={1}
      overflow={overflow ?? (orb ? "hidden" : undefined)}
      py={{
        base: compact ? "40px" : "52px",
        md: compact ? "64px" : "84px",
        xl: compact ? "80px" : "104px",
      }}
      borderTop={tinted ? `1px solid ${colors.border.faint}` : undefined}
      borderBottom={tinted ? `1px solid ${colors.border.faint}` : undefined}
      bg={tinted ? gradients.sectionTint : undefined}
      {...rest}
    >
      {orb && <Box className={`section-orb section-orb-${orb}`} aria-hidden />}
      <Box position="relative" zIndex={1}>
        {children}
      </Box>
    </Box>
  );
}

/** Редакторский сплит: узкая колонка заголовка + широкая колонка контента. */
export function SplitLayout({ children, ...rest }) {
  return (
    <Grid
      templateColumns={{ base: "1fr", lg: "minmax(280px, 0.82fr) minmax(0, 1.18fr)" }}
      gap={{ base: "24px", md: "36px", lg: "60px" }}
      alignItems="start"
      {...rest}
    >
      {children}
    </Grid>
  );
}
