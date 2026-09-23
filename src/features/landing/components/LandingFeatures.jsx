import React from "react";
import { Link as RouterLink } from "react-router-dom";
import { FiArrowRight } from "@shared/icons";
import MagneticButton from "@shared/controls/MagneticButton";
import { colors } from "@theme/tokens";
import { Reveal } from "@shared/motion/Reveal";
import { LANDING_FEATURES } from "@/content/landing";
import { LANDING_ICONS } from "./iconMap";
import SectionHeading from "@shared/marketing/SectionHeading";
import AgentOrbit from "@shared/marketing/AgentOrbit";
import { Section, PageShell, SplitLayout } from "@shared/marketing/primitives";

// Цвет узла на возможность (палитра агентов) — «живая» орбита оркестрации
// вместо ровной сетки карточек.
const NODE_COLORS = [
  colors.agents.general,
  colors.agents.web_search,
  colors.agents.image_gen,
  colors.agents.pptx_gen,
  colors.agents.deep_research,
  colors.agents.audio_transcribe,
];

export default function LandingFeatures() {
  const orbitItems = LANDING_FEATURES.items.map((item, i) => ({
    key: item.title,
    icon: LANDING_ICONS[item.icon],
    title: item.title,
    description: item.description,
    color: NODE_COLORS[i % NODE_COLORS.length],
  }));

  return (
    <Section id="features" orb="blue">
      <PageShell>
        {/* Сплит: заголовок слева, живая орбита с подписью — справа. Раньше
            орбита висела ПОД заголовком, из-за чего вся правая половина секции
            простаивала. */}
        <SplitLayout
          templateColumns={{ base: "1fr", lg: "1fr minmax(0, 700px)" }}
          alignItems="center"
        >
          <SectionHeading
            align="left"
            size="md"
            index="01"
            eyebrow={LANDING_FEATURES.eyebrow}
            title={LANDING_FEATURES.title}
            copy={LANDING_FEATURES.subtitle}
            mb={0}
            action={
              <MagneticButton
                as={RouterLink}
                to={LANDING_FEATURES.action.to}
                variant="secondary"
                size="md"
                rightIcon={<FiArrowRight />}
              >
                {LANDING_FEATURES.action.label}
              </MagneticButton>
            }
          />
          <Reveal variant="rise">
            <AgentOrbit items={orbitItems} />
          </Reveal>
        </SplitLayout>
      </PageShell>
    </Section>
  );
}
