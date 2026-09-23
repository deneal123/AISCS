import React from "react";
import { Box } from "@chakra-ui/react";
import CtaBand from "@shared/marketing/CtaBand";
import { LANDING_CTA } from "@/content/landing";

export default function LandingCTA() {
  return (
    <Box as="section" id="cta" w="100%" maxW="1520px" mx="auto" px={{ base: 5, md: 8, lg: 12 }} pb={{ base: 24, md: 32 }} pt={{ base: 4, md: 8 }}>
      <CtaBand
        title={LANDING_CTA.title}
        subtitle={LANDING_CTA.subtitle}
        primaryCta={LANDING_CTA.primaryCta}
        secondaryCta={LANDING_CTA.secondaryCta}
      />
    </Box>
  );
}
