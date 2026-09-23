import React, { useRef, useState } from "react";
import { Box, Grid, HStack, SimpleGrid, Text, VStack, Wrap, WrapItem } from "@chakra-ui/react";
import { Link as RouterLink } from "react-router-dom";
import MagneticButton from "@shared/controls/MagneticButton";
import { FiArrowRight } from "@shared/icons";
import { colors } from "@theme/tokens";
import { Reveal } from "@shared/motion/Reveal";
import Eyebrow from "@shared/brand/Eyebrow";
import TagPill from "@shared/brand/TagPill";
import SectionHeading from "@shared/marketing/SectionHeading";
import MetricCounter from "@shared/marketing/MetricCounter";
import CtaBand from "@shared/marketing/CtaBand";
import { prefersReducedMotion } from "@utils/motion";
import {
  PLATFORM_HERO, PLATFORM_SHOWCASE, PLATFORM_ORCHESTRATION, PLATFORM_ROSTER, PLATFORM_CTA,
} from "@/content/platform";
import ChatShowcase from "../components/ChatShowcase";
import ChatWindow from "../components/ChatWindow";
import ConversationTurn from "../components/ConversationTurn";
import FlowRail from "../components/FlowRail";
import AgentRoster from "../components/AgentRoster";

function Section({ id, children, orb, minH, pt, innerRef }) {
  return (
    <Box
      as="section"
      id={id}
      ref={innerRef}
      position="relative"
      w="100%"
      maxW="1520px"
      mx="auto"
      px={{ base: 5, md: 8, lg: 12 }}
      py={{ base: 16, md: 24 }}
      pt={pt}
      minH={minH}
      display={minH ? "flex" : undefined}
      flexDirection={minH ? "column" : undefined}
      justifyContent={minH ? "center" : undefined}
      overflow="hidden"
    >
      {orb && <Box className={`section-orb section-orb-${orb}`} aria-hidden />}
      <Box position="relative" zIndex={1} w="100%">{children}</Box>
    </Box>
  );
}

function HeroCtas({ primary, secondary }) {
  return (
    <HStack spacing={3} flexWrap="wrap" justify={{ base: "center", lg: "flex-start" }}>
      <MagneticButton as={RouterLink} to={primary.to} variant="primary" size="lg"
        rightIcon={<FiArrowRight />}>
        {primary.label}
      </MagneticButton>
      <MagneticButton as={RouterLink} to={secondary.to} variant="secondary" size="lg">
        {secondary.label}
      </MagneticButton>
    </HStack>
  );
}

function StrategyChip({ label, hint }) {
  return (
    <HStack
      spacing={2}
      px={4}
      py={2}
      borderRadius="full"
      bg={colors.surface.tint2}
      border={`1px solid ${colors.border.subtle}`}
    >
      <Text fontSize="13px" fontWeight="600" color={colors.fg[1]}>{label}</Text>
      <Text fontSize="11px" color={colors.fg[4]}>· {hint}</Text>
    </HStack>
  );
}

export default function PlatformPage() {
  const [activeKey, setActiveKey] = useState(PLATFORM_SHOWCASE.conversations[0].key);
  const showcaseRef = useRef(null);

  const handleRosterSelect = (key) => {
    setActiveKey(key);
    showcaseRef.current?.scrollIntoView({
      behavior: prefersReducedMotion() ? "auto" : "smooth",
      block: "start",
    });
  };

  return (
    <Box position="relative" zIndex={1} w="100%" overflowX="hidden">
      {/* HERO — сплит, владеет фолдом; живое чат-окно (на мобиле — стеком снизу) */}
      <Section id="platform-hero" orb="blue" minH={{ lg: "calc(100svh - var(--app-header-h))" }} pt={{ base: 10, md: 14 }}>
        <Grid templateColumns={{ base: "1fr", lg: "1.02fr 0.98fr" }} gap={{ base: 10, lg: 12 }} alignItems="center">
          <Reveal variant="rise">
            <VStack align={{ base: "center", lg: "flex-start" }} textAlign={{ base: "center", lg: "left" }} spacing={6}>
              <Eyebrow>{PLATFORM_HERO.eyebrow}</Eyebrow>
              <Text as="h1" fontSize={{ base: "32px", md: "50px" }} fontWeight="800"
                letterSpacing="-0.03em" lineHeight="1.06" color={colors.fg[1]} maxW="640px">
                {PLATFORM_HERO.titleLead}{" "}
                <Box as="span" className="iridescent-text">{PLATFORM_HERO.titleAccent}</Box>
              </Text>
              <Text fontSize={{ base: "16px", md: "18px" }} color={colors.fg[3]} lineHeight="1.6" maxW="620px">
                {PLATFORM_HERO.subtitle}
              </Text>
              <Wrap spacing={2.5} justify={{ base: "center", lg: "flex-start" }} pt={1}>
                {PLATFORM_HERO.tags.map((tag) => (
                  <WrapItem key={tag}><TagPill>{tag}</TagPill></WrapItem>
                ))}
              </Wrap>
              <Box pt={2}>
                <HeroCtas primary={PLATFORM_HERO.primaryCta} secondary={PLATFORM_HERO.secondaryCta} />
              </Box>
              <Text fontSize="13px" color={colors.fg[4]}>{PLATFORM_HERO.note}</Text>
            </VStack>
          </Reveal>

          <Reveal variant="rise" delay={140}>
            <ChatWindow title="GPTHub · Ассистент">
              <ConversationTurn conversation={PLATFORM_HERO.demo} />
            </ChatWindow>
          </Reveal>
        </Grid>
      </Section>

      {/* SHOWCASE — витрина диалогов (ядро) */}
      <Section id="platform-showcase" orb="violet" innerRef={showcaseRef}>
        <SectionHeading eyebrow={PLATFORM_SHOWCASE.eyebrow} title={PLATFORM_SHOWCASE.title} copy={PLATFORM_SHOWCASE.subtitle} align="left" size="md" index="01" />
        <Reveal variant="rise">
          <ChatShowcase activeKey={activeKey} onSelect={setActiveKey} />
        </Reveal>
      </Section>

      {/* ORCHESTRATION — визуальный flow-rail + стратегии + слим-статистика */}
      <Section id="platform-how" orb="blue">
        <SectionHeading eyebrow={PLATFORM_ORCHESTRATION.eyebrow} title={PLATFORM_ORCHESTRATION.title} copy={PLATFORM_ORCHESTRATION.subtitle} align="left" size="md" index="02" />
        <Reveal variant="rise"><FlowRail flow={PLATFORM_ORCHESTRATION.flow} /></Reveal>
        <Reveal variant="soft" as={Wrap} justify="flex-start" spacing={3} mt={{ base: 8, md: 12 }}>
          {PLATFORM_ORCHESTRATION.strategies.map((s) => (
            <WrapItem key={s.label}><StrategyChip label={s.label} hint={s.hint} /></WrapItem>
          ))}
        </Reveal>
        <Reveal className="stagger-children" as={SimpleGrid} columns={{ base: 3 }}
          mt={{ base: 12, md: 16 }} spacing={{ base: 4, md: 10 }} borderTop={`1px solid ${colors.border.subtle}`} pt={{ base: 8, md: 10 }}>
          {PLATFORM_ORCHESTRATION.stats.map((m) => (
            <MetricCounter key={m.label} value={m.value} suffix={m.suffix} label={m.label} align="left" />
          ))}
        </Reveal>
      </Section>

      {/* ROSTER — тонированная панель «команда агентов» (ритм-перебой) */}
      <Box as="section" id="platform-roster" position="relative" w="100%"
        bg={colors.bg.panel} borderY={`1px solid ${colors.border.subtle}`} overflow="hidden">
        <Box className="section-orb section-orb-violet" aria-hidden />
        <Box position="relative" zIndex={1} maxW="1520px" mx="auto" px={{ base: 5, md: 8, lg: 12 }} py={{ base: 16, md: 24 }}>
          <SectionHeading eyebrow={PLATFORM_ROSTER.eyebrow} title={PLATFORM_ROSTER.title} copy={PLATFORM_ROSTER.subtitle} align="left" size="md" index="03" />
          <Reveal variant="rise"><AgentRoster onSelect={handleRosterSelect} /></Reveal>
        </Box>
      </Box>

      {/* CTA — общий CtaBand (scan) */}
      <Section id="platform-cta">
        <CtaBand
          title={PLATFORM_CTA.title}
          subtitle={PLATFORM_CTA.subtitle}
          primaryCta={PLATFORM_CTA.primaryCta}
          secondaryCta={PLATFORM_CTA.secondaryCta}
        />
      </Section>
    </Box>
  );
}
