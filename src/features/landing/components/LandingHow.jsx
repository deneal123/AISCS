import React from "react";
import { Box } from "@chakra-ui/react";
import { Link as RouterLink } from "react-router-dom";
import MagneticButton from "@shared/controls/MagneticButton";
import { FiArrowRight } from "@shared/icons";
import { LANDING_HOW } from "@/content/landing";
import SectionHeading from "@shared/marketing/SectionHeading";
import StepList from "@shared/marketing/StepList";
import { Section, PageShell, SplitLayout } from "@shared/marketing/primitives";

export default function LandingHow() {
  return (
    <Section id="how" orb="blue">
      <PageShell>
        <SplitLayout>
          <Box position={{ lg: "sticky" }} top={{ lg: "120px" }}>
            <SectionHeading
              eyebrow={LANDING_HOW.eyebrow}
              title={LANDING_HOW.title}
              copy={LANDING_HOW.subtitle}
              align="left"
              size="md"
              index="03"
              mb={0}
              action={
                <MagneticButton
                  as={RouterLink}
                  to={LANDING_HOW.action.to}
                  variant="secondary"
                  size="md"
                  rightIcon={<FiArrowRight />}
                >
                  {LANDING_HOW.action.label}
                </MagneticButton>
              }
            />
          </Box>
          <Box>
            <StepList steps={LANDING_HOW.steps} />
          </Box>
        </SplitLayout>
      </PageShell>
    </Section>
  );
}
