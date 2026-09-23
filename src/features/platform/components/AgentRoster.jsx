import React from "react";
import { Box, Grid, HStack, Icon, Text, VStack } from "@chakra-ui/react";
import { FiCode, FiFileText, FiGlobe, FiImage, FiPaperclip, FiSearch, FiArrowUpRight } from "@shared/icons";
import { colors, motion } from "@theme/tokens";
import { GLASS_CARD_BASE } from "@theme/glass";
import { AGENT_META, PLATFORM_SHOWCASE } from "@/content/platform";

const ICONS = { FiSearch, FiGlobe, FiImage, FiFileText, FiCode, FiPaperclip };

function RosterCard({ conv, onSelect }) {
  const meta = AGENT_META[conv.agent] || AGENT_META.general;
  const CardIcon = ICONS[conv.icon] || FiSearch;
  return (
    <Box
      as="button"
      type="button"
      onClick={() => onSelect(conv.key)}
      textAlign="left"
      p={{ base: 4, md: 5 }}
      position="relative"
      overflow="hidden"
      {...GLASS_CARD_BASE}
      transition={`transform 220ms ${motion.easeOut}, border-color 220ms ${motion.easeOut}, box-shadow 220ms ${motion.easeOut}`}
      _hover={{ transform: "translateY(-3px)", borderColor: `${meta.color}66`, boxShadow: `0 12px 32px ${meta.color}22` }}
      _focusVisible={{ outline: "none", boxShadow: `0 0 0 2px ${meta.color}88` }}
    >
      {/* Левый акцент-бар агент-цветом */}
      <Box position="absolute" top={0} left={0} bottom={0} w="3px" bg={meta.color} opacity={0.85} />
      <VStack align="flex-start" spacing={3} pl={1}>
        <HStack justify="space-between" w="100%">
          <Box
            boxSize="38px"
            borderRadius="11px"
            bg={`${meta.color}1a`}
            border={`1px solid ${meta.color}44`}
            display="flex"
            alignItems="center"
            justifyContent="center"
          >
            <Icon as={CardIcon} boxSize="18px" color={meta.color} />
          </Box>
          <Icon as={FiArrowUpRight} boxSize="16px" color={colors.fg[4]} />
        </HStack>
        <Box>
          <Text fontSize="15px" fontWeight="700" color={colors.fg[1]}>{conv.tab}</Text>
          <Text fontSize="13px" color={colors.fg[3]} lineHeight="1.5" mt={1}>{conv.summary}</Text>
        </Box>
      </VStack>
    </Box>
  );
}

/** Ростер «команды агентов» — карточки открывают соответствующий пример в витрине. */
export default function AgentRoster({ onSelect }) {
  return (
    <Grid templateColumns={{ base: "1fr", sm: "repeat(2, 1fr)", lg: "repeat(3, 1fr)" }} gap={{ base: 4, md: 5 }}>
      {PLATFORM_SHOWCASE.conversations.map((conv) => (
        <RosterCard key={conv.key} conv={conv} onSelect={onSelect} />
      ))}
    </Grid>
  );
}
