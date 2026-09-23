import React from "react";
import { Box } from "@chakra-ui/react";
import { LANDING_USE_CASES } from "@/content/landing";
import { LANDING_ICONS } from "./iconMap";
import SectionHeading from "@shared/marketing/SectionHeading";
import FeatureRow from "@shared/marketing/FeatureRow";
import { Section, PageShell } from "@shared/marketing/primitives";

export default function LandingUseCases() {
  return (
    <Section id="use-cases" orb="violet">
      <PageShell>
        <Box>
          <SectionHeading
            eyebrow={LANDING_USE_CASES.eyebrow}
            title={LANDING_USE_CASES.title}
            copy={LANDING_USE_CASES.subtitle}
            align="left"
            size="md"
            index="02"
          />
          <FeatureRow
            items={LANDING_USE_CASES.items.map((item) => ({
              icon: LANDING_ICONS[item.icon],
              title: item.title,
              description: item.description,
            }))}
          />
        </Box>
      </PageShell>
    </Section>
  );
}
