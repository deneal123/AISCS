import React from "react";
import { Box, Flex, HStack, Icon, Text, VStack, Tooltip } from "@chakra-ui/react";
import {
  FiMessageSquare, FiGitBranch, FiCpu, FiCheckCircle, FiChevronRight, FiChevronDown,
} from "@shared/icons";
import { colors } from "@theme/tokens";
import { AGENT_META, PLATFORM_SHOWCASE } from "@/content/platform";

const ICONS = { FiMessageSquare, FiGitBranch, FiCpu, FiCheckCircle };

// Шесть агентов витрины (для «ветвления» на узле оркестратора).
const AGENT_DOTS = PLATFORM_SHOWCASE.conversations.map((c) => ({
  key: c.key,
  label: (AGENT_META[c.agent] || AGENT_META.general).label,
  color: (AGENT_META[c.agent] || AGENT_META.general).color,
}));

function AgentDots() {
  return (
    <HStack spacing={1.5} pt={1} justify="center" flexWrap="wrap" maxW="180px">
      {AGENT_DOTS.map((a) => (
        <Tooltip key={a.key} label={a.label} placement="top" hasArrow openDelay={200} fontSize="11px">
          <Box
            boxSize="11px"
            borderRadius="full"
            bg={`${a.color}cc`}
            border={`1px solid ${a.color}`}
            boxShadow={`0 0 6px ${a.color}66`}
          />
        </Tooltip>
      ))}
    </HStack>
  );
}

function FlowNode({ node, isAgents }) {
  const NodeIcon = ICONS[node.icon] || FiCpu;
  return (
    <VStack spacing={2.5} flex="1" minW={0} textAlign="center" px={2}>
      <Box
        boxSize="52px"
        borderRadius="15px"
        bg={colors.accent.soft}
        border={`1px solid ${colors.accent.subtleBorder}`}
        display="flex"
        alignItems="center"
        justifyContent="center"
      >
        <Icon as={NodeIcon} boxSize="22px" color={colors.blue[300]} />
      </Box>
      <Text fontSize="15px" fontWeight="700" color={colors.fg[1]}>{node.title}</Text>
      <Text fontSize="12.5px" color={colors.fg[3]} lineHeight="1.5" maxW="200px">{node.description}</Text>
      {isAgents && <AgentDots />}
    </VStack>
  );
}

function Connector() {
  return (
    <Flex align="center" justify="center" flexShrink={0} py={{ base: 1, lg: 0 }} px={{ base: 0, lg: 1 }}
      color={colors.iris[300]} opacity={0.7} aria-hidden mt={{ lg: "26px" }}>
      <Icon as={FiChevronRight} boxSize="20px" display={{ base: "none", lg: "block" }} />
      <Icon as={FiChevronDown} boxSize="18px" display={{ base: "block", lg: "none" }} />
    </Flex>
  );
}

/** Оркестрация как визуальный «поток»: Запрос → Оркестратор → Агент(ы) → Результат. */
export default function FlowRail({ flow = [] }) {
  return (
    <Flex direction={{ base: "column", lg: "row" }} align="stretch" justify="center" gap={0} maxW="1000px" mx="auto">
      {flow.map((node, i) => (
        <React.Fragment key={node.title}>
          <FlowNode node={node} isAgents={i === 2} />
          {i < flow.length - 1 && <Connector />}
        </React.Fragment>
      ))}
    </Flex>
  );
}
