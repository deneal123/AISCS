import React from "react";
import { Box, Link } from "@chakra-ui/react";
import { Link as RouterLink } from "react-router-dom";
import { colors } from "@theme/tokens";
import { LANDING_TRUST } from "@/content/landing";
import { LANDING_ICONS } from "./iconMap";
import SectionHeading from "@shared/marketing/SectionHeading";
import FeatureRow from "@shared/marketing/FeatureRow";
import { Section, PageShell } from "@shared/marketing/primitives";

export default function LandingTrust() {
  return (
    <Section id="trust" orb="blue">
      <PageShell>
        <Box>
          <SectionHeading
            eyebrow={LANDING_TRUST.eyebrow}
            title={LANDING_TRUST.title}
            align="left"
            size="md"
            index="05"
            action={
              <Link
                as={RouterLink}
                to={LANDING_TRUST.action.to}
                display="inline-flex"
                alignItems="center"
                gap={1.5}
                minH="44px"
                color={colors.blue[300]}
                fontSize="14px"
                fontWeight="700"
                _hover={{ color: colors.fg[1], textDecoration: "none" }}
              >
                {LANDING_TRUST.action.label}
                <Box as="span" className="link-arrow" aria-hidden>↗</Box>
              </Link>
            }
          />
          <FeatureRow
            columns={1}
            items={LANDING_TRUST.items.map((item) => ({
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
