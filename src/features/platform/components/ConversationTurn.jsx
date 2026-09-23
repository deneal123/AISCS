import React from "react";
import { Box, HStack, Icon, Text, VStack, keyframes } from "@chakra-ui/react";
import { FiZap, FiFile, FiDownload, FiImage } from "@shared/icons";
import { colors, borderRadius, shadows, motion } from "@theme/tokens";
import { useInView } from "@hooks/useInView";
import { AGENT_META } from "@/content/platform";
import { useStagedReveal } from "../hooks/useStagedReveal";
import ActivityTrace from "./ActivityTrace";
import MockMarkdown from "./MockMarkdown";
import MockCodeBlock from "./MockCodeBlock";

const enter = keyframes`
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
`;

function Attachment({ name, kind }) {
  return (
    <HStack
      spacing={2}
      px={2.5}
      py={1.5}
      borderRadius={borderRadius.sm}
      bg={colors.bg.input}
      border={`1px solid ${colors.glass.border}`}
    >
      <Icon as={FiFile} boxSize="13px" color={colors.iris[300]} />
      <Text fontSize="12px" color={colors.fg[2]} fontWeight="500">{name}</Text>
      {kind && <Text fontSize="10.5px" color={colors.fg[4]}>· {kind}</Text>}
    </HStack>
  );
}

// Артефакт результата: сгенерированное изображение (иллюстративный арт-плейсхолдер,
// тёплые hex — P3 one-off, не токенизируем) или .pptx-файл (на токенах).
function Artifact({ artifact }) {
  if (!artifact) return null;
  if (artifact.type === "image") {
    return (
      <Box mt={3} maxW="300px">
        <Box
          h="180px"
          borderRadius={borderRadius.md}
          border={`1px solid ${colors.glass.border}`}
          position="relative"
          overflow="hidden"
          sx={{
            background:
              "radial-gradient(120% 120% at 30% 20%, #F5B463 0%, #E8804B 38%, #7A4A2F 72%, #2A1A12 100%)",
          }}
        >
          <Box position="absolute" inset={0} display="flex" alignItems="center" justifyContent="center">
            <Box
              boxSize="72px"
              borderRadius="18px"
              bg="rgba(20,12,8,0.55)"
              border="1.5px solid rgba(255,255,255,0.5)"
              display="flex"
              alignItems="center"
              justifyContent="center"
              backdropFilter="blur(2px)"
            >
              <Text fontSize="30px" fontWeight="800" color="#FFF6EC" letterSpacing="-0.02em">☕</Text>
            </Box>
          </Box>
          <HStack position="absolute" top={2} left={2} spacing={1.5} px={2} py={1}
            borderRadius="full" bg="rgba(0,0,0,0.4)">
            <Icon as={FiImage} boxSize="11px" color="whiteAlpha.800" />
            <Text fontSize="10px" color="whiteAlpha.800" fontWeight="600">пример вывода</Text>
          </HStack>
        </Box>
        {artifact.caption && (
          <Text mt={1.5} fontSize="11.5px" color={colors.fg[4]}>{artifact.caption}</Text>
        )}
      </Box>
    );
  }
  if (artifact.type === "pptx") {
    return (
      <HStack
        mt={3}
        spacing={2.5}
        px={3.5}
        py={2.5}
        borderRadius={borderRadius.md}
        bg={colors.accent.subtle}
        border={`1px solid ${colors.accent.subtleBorder}`}
        w="fit-content"
        maxW="100%"
      >
        <Icon as={FiDownload} boxSize="16px" color={colors.blue[300]} />
        <Box>
          <Text fontSize="13px" fontWeight="600" color={colors.fg[1]}>Скачать презентацию</Text>
          <Text fontSize="11px" color={colors.fg[4]}>{artifact.filename}</Text>
        </Box>
      </HStack>
    );
  }
  return null;
}

/**
 * Один диалог: запрос пользователя → трейс → ответ агента (+ артефакт),
 * с поэтапным показом (пузырь → шаги трейса тикают → ответ) при въезде во вьюпорт.
 */
export default function ConversationTurn({ conversation }) {
  const meta = AGENT_META[conversation.agent] || AGENT_META.general;
  const showBadge = meta.label !== "Ассистент";
  const trace = conversation.trace || [];

  const [ref, inView] = useInView(0.3);
  const total = 2 + trace.length; // пузырь + N шагов трейса + ответ
  const shown = useStagedReveal(total, { active: inView });

  const showBubble = shown >= 1;
  const traceReveal = Math.max(0, Math.min(shown - 1, trace.length));
  const showResponse = shown >= total;

  return (
    <VStack ref={ref} align="stretch" spacing={0} w="100%" minH="60px">
      {/* Пузырь пользователя (справа) */}
      {showBubble && (
        <Box display="flex" justifyContent="flex-end" w="100%" animation={`${enter} 340ms ${motion.easeOut}`}>
          <VStack align="flex-end" spacing={2} maxW={{ base: "92%", md: "82%" }}>
            {conversation.attachments?.length > 0 && (
              <HStack spacing={2} flexWrap="wrap" justify="flex-end">
                {conversation.attachments.map((a) => <Attachment key={a.name} {...a} />)}
              </HStack>
            )}
            <Box
              px={{ base: 4, md: 5 }}
              py={3}
              borderRadius="20px 20px 10px 20px"
              bg={colors.accent.subtle}
              border={`1px solid ${colors.accent.subtleBorder}`}
              boxShadow={shadows.glowUser}
            >
              <Text fontSize={{ base: "14px", md: "14.5px" }} color={colors.fg[1]} fontWeight="500"
                lineHeight="1.6" whiteSpace="pre-wrap">
                {conversation.query}
              </Text>
            </Box>
            {conversation.queryCode && (
              <Box w={{ base: "100%", sm: "420px" }} maxW="100%">
                <MockCodeBlock language={conversation.queryCode.language} value={conversation.queryCode.value} />
              </Box>
            )}
          </VStack>
        </Box>
      )}

      {/* Трейс работы агентов — тикает по одному шагу */}
      <ActivityTrace steps={trace} revealIndex={traceReveal} />

      {/* Ответ агента (слева, во всю ширину) */}
      {showResponse && (
        <Box mt={5} w="100%" animation={`${enter} 380ms ${motion.easeOut}`}>
          <HStack spacing={2.5} mb={2} align="center">
            <Box
              boxSize="28px"
              borderRadius="9px"
              bg={colors.accent.subtle}
              border={`1px solid ${colors.accent.subtleBorder}`}
              boxShadow={shadows.glowSubtle}
              display="flex"
              alignItems="center"
              justifyContent="center"
              flexShrink={0}
            >
              <Icon as={FiZap} boxSize="14px" color={colors.blue[300]} />
            </Box>
            <Text fontSize="13px" fontWeight="650" color={colors.fg[1]}>Ассистент</Text>
            {showBadge && (
              <Text
                as="span"
                fontSize="10px"
                fontWeight="700"
                borderRadius="full"
                px={2}
                py="1px"
                color={meta.color}
                border={`1px solid ${meta.color}55`}
                bg={`${meta.color}14`}
              >
                {meta.label}
              </Text>
            )}
            <Text fontSize="11px" color={colors.fg[4]}>сейчас</Text>
          </HStack>
          <MockMarkdown content={conversation.response} />
          <Artifact artifact={conversation.artifact} />
        </Box>
      )}
    </VStack>
  );
}
