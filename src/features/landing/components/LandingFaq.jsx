import React from "react";
import { Box, Icon, Text, VStack } from "@chakra-ui/react";
import { FiChevronDown } from "@shared/icons";
import { Reveal } from "@shared/motion/Reveal";
import { LANDING_FAQ } from "@/content/landing";
import SectionHeading from "@shared/marketing/SectionHeading";
import { Section } from "@shared/marketing/primitives";

/**
 * FAQ-аккордеон на native <details>/<summary> (стекло, chevron-rotate, dc-body-in).
 * Open-state стили в src/styles/motion.css (Chakra не таргетит [open]).
 */
export default function LandingFaq() {
  return (
    <Section id="faq">
      <Box w="100%" maxW="820px" mx="auto" px="clamp(20px, 4vw, 56px)">
        <SectionHeading eyebrow={LANDING_FAQ.eyebrow} title={LANDING_FAQ.title} align="left" size="md" index="06" />
        <Reveal className="stagger-children" as={VStack} align="stretch" spacing={3}>
          {LANDING_FAQ.items.map((item) => (
            <Box as="details" key={item.q} className="disclosure">
              <Box as="summary">
                <Text as="span">{item.q}</Text>
                <Icon as={FiChevronDown} className="disclosure-chevron" boxSize="18px" />
              </Box>
              <Box className="disclosure-body">{item.a}</Box>
            </Box>
          ))}
        </Reveal>
      </Box>
    </Section>
  );
}
