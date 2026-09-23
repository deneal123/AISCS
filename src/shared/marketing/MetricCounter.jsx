import React from "react";
import { Box, Text, VStack } from "@chakra-ui/react";
import { colors, typography, gradients } from "@theme/tokens";
import { useInView } from "@hooks/useInView";
import { useCountUp } from "@hooks/useCountUp";

/** Метрика с gradient-числом и count-up при попадании во вьюпорт (лёгкая геймификация). */
export default function MetricCounter({ value, suffix = "", label, align = "center" }) {
  const [ref, inView] = useInView(0.4);
  const animated = useCountUp(value, { active: inView });
  const display = Math.round(animated);

  return (
    <VStack ref={ref} spacing={1.5} align={align === "left" ? "flex-start" : "center"} textAlign={align === "left" ? "left" : "center"}>
      <Box
        fontSize={{ base: "40px", md: "52px" }}
        fontWeight="800"
        lineHeight="1"
        letterSpacing="-0.02em"
        sx={{
          background: gradients.metricNumber,
          backgroundClip: "text",
          WebkitBackgroundClip: "text",
          WebkitTextFillColor: "transparent",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {display}
        {suffix}
      </Box>
      <Text fontSize="12px" fontWeight="600" letterSpacing="0.06em" textTransform="uppercase" color={colors.fg[4]} fontFamily={typography.fontFamily.mono} maxW="200px">
        {label}
      </Text>
    </VStack>
  );
}
