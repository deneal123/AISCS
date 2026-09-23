import React, { useEffect, useState } from "react";
import { Box, HStack, Icon, Text, VStack, keyframes } from "@chakra-ui/react";
import {
  FiActivity, FiAlertCircle, FiCheck, FiCpu, FiGitBranch, FiSearch, FiTool,
} from "@shared/icons";
import { colors, borderRadius, motion } from "@theme/tokens";
import { AGENT_META } from "@/content/platform";

const stepIn = keyframes`
  from { opacity: 0; transform: translateY(6px); }
  to   { opacity: 1; transform: translateY(0); }
`;

// Иконка шага по ключевым словам заголовка/типа — как pickIcon в чат-трейсе.
function pickIcon(step) {
  if (step.kind === "error") return FiAlertCircle;
  const t = (step.title || "").toLowerCase();
  if (/маршрут|выбран агент/.test(t)) return FiGitBranch;
  if (/инструмент|tool/.test(t)) return FiTool;
  if (/поиск|исслед|источ/.test(t)) return FiSearch;
  if (/сформирован|готов|заверш/.test(t)) return FiCheck;
  if (/агент|модел|мультимодальн/.test(t)) return FiCpu;
  return FiActivity;
}

// Прогресс-бар с анимированной заливкой 0→target при появлении шага.
function ProgressBar({ progress }) {
  const [w, setW] = useState(0);
  useEffect(() => {
    const id = requestAnimationFrame(() => setW(progress));
    return () => cancelAnimationFrame(id);
  }, [progress]);
  return (
    <Box mt={2} maxW="320px">
      <HStack justify="space-between" mb={1}>
        <Text fontSize="10.5px" color={colors.fg[3]}>Прогресс</Text>
        <Text fontSize="10.5px" fontWeight="600" color={colors.blue[300]} fontFamily="'JetBrains Mono', monospace">
          {progress}%
        </Text>
      </HStack>
      <Box h="6px" borderRadius="full" bg={colors.border.subtle} overflow="hidden">
        <Box
          h="100%"
          w={`${w}%`}
          borderRadius="full"
          bg={colors.blue[500]}
          boxShadow={`0 0 8px ${colors.accent.glow}`}
          transition={`width 900ms ${motion.easeOut}`}
        />
      </Box>
    </Box>
  );
}

/**
 * Реплика строки активности / трейса чата для витрины /platform.
 * steps: [{ title, detail?, agent, kind:'info'|'done'|'error', progress? }].
 * revealIndex — сколько шагов показать (поэтапный «тик»); по умолчанию все.
 * Пилюлю агента показываем только на смене агента (подсветка передач).
 */
export default function ActivityTrace({ steps = [], revealIndex }) {
  const count = revealIndex == null ? steps.length : Math.max(0, Math.min(revealIndex, steps.length));
  const visible = steps.slice(0, count);
  if (visible.length === 0) return null;

  return (
    <Box
      mt={4}
      px={4}
      py={3}
      borderRadius={borderRadius.md}
      bg={colors.glass.bg}
      border={`1px solid ${colors.glass.border}`}
    >
      <VStack spacing={0} align="stretch">
        {visible.map((step, i) => {
          const meta = AGENT_META[step.agent] || AGENT_META.general;
          const StepIcon = pickIcon(step);
          const isLast = i === visible.length - 1;
          const showPill = i === 0 || step.agent !== visible[i - 1].agent;
          return (
            <HStack
              key={i}
              align="flex-start"
              spacing={2.5}
              animation={`${stepIn} 300ms ${motion.easeOut}`}
            >
              {/* Левый рельс: иконка-чип + коннектор */}
              <VStack spacing={0} align="center" minW="16px" alignSelf="stretch">
                <Box
                  boxSize="16px"
                  borderRadius="full"
                  bg={`${meta.color}1f`}
                  border={`1px solid ${meta.color}66`}
                  display="flex"
                  alignItems="center"
                  justifyContent="center"
                  flexShrink={0}
                  mt="1px"
                >
                  <Icon as={StepIcon} boxSize="9px" color={meta.color} />
                </Box>
                {!isLast && <Box w="1.5px" flex="1" minH="12px" bg={colors.border.hairline} my={1} />}
              </VStack>

              {/* Тело шага */}
              <Box flex="1" pb={isLast ? 0 : 2.5} minW={0}>
                <HStack spacing={2} align="center" flexWrap="wrap">
                  <Text fontSize="13px" fontWeight="600" color={step.kind === "error" ? colors.error : colors.fg[1]} noOfLines={1}>
                    {step.title}
                  </Text>
                  {showPill && (
                    <Text
                      as="span"
                      fontSize="9.5px"
                      fontWeight="700"
                      letterSpacing="0.08em"
                      textTransform="uppercase"
                      color={meta.color}
                      border={`1px solid ${meta.color}66`}
                      borderRadius="full"
                      px={1.5}
                      py="1px"
                      flexShrink={0}
                    >
                      {meta.label}
                    </Text>
                  )}
                </HStack>
                {step.detail && (
                  <Text fontSize="11.5px" color={colors.fg[4]} mt={0.5} lineHeight="1.45" noOfLines={2}>
                    {step.detail}
                  </Text>
                )}
                {typeof step.progress === "number" && <ProgressBar progress={step.progress} />}
              </Box>
            </HStack>
          );
        })}
      </VStack>
    </Box>
  );
}
