import React from 'react';
import { Box, Center, Grid, HStack, Icon, Text, VStack } from '@chakra-ui/react';
import { FiActivity, FiBarChart2, FiCheck, FiCompass, FiSearch, FiTool, FiUser, FiUsers, FiZap } from '@shared/icons';
import { colors, borderRadius, gradients, shadows, typography } from '@theme/tokens';
import { GLASS_CARD_BASE, CARD_TOP_LINE, CARD_HOVER_STATE } from '@theme/glass';
import Eyebrow from '@shared/brand/Eyebrow';
import { Reveal } from '@shared/motion/Reveal';
import { CHAT_FONT_FAMILY, CHAT_THEME } from '../constants/theme';
import { MAX_PERSONAS } from './composer/ComposerPersonaSelector';
import ChatOnboarding from './ChatOnboarding';

// Иконка по id личности: реестр редактируется в админке и иконок не знает (и не должен —
// это визуальный слой). Незнакомый id получает нейтральную, поэтому новая личность
// появляется в интерфейсе сразу после правки JSON, без выката фронта.
const PERSONA_ICONS = {
  analyst: FiBarChart2,
  engineer: FiTool,
  psychologist: FiUsers,
  financier: FiActivity,
  scientist: FiSearch,
  tarot: FiCompass,
};

/** Пустое состояние чата: выбор личности + онбординг.
 *
 * ⚠️ Раньше здесь были стена шаблонов-брифов и кнопки режимов. Убраны намеренно: шаблон —
 * разовая подсказка «что написать», а личность задаёт, КАК агент будет думать над всеми
 * следующими сообщениями, включая то, что он замечает во вложениях, поиске и данных.
 * Режимы (веб-поиск, изображение, презентация) остались в композере, где им и место: это
 * выбор «что сделать сейчас», а не характер собеседника.
 */
export default function ChatEmptyState({
  personas = [],
  personaIds = [],
  onPersonaIdsChange,
  onboarding,
}) {
  const selected = Array.isArray(personaIds) ? personaIds : [];
  const atCap = selected.length >= MAX_PERSONAS;

  const toggle = (id) => {
    if (selected.includes(id)) {
      onPersonaIdsChange?.(selected.filter((x) => x !== id));
      return;
    }
    if (atCap) return;
    onPersonaIdsChange?.([...selected, id]);
  };

  return (
    <Center minH="60vh">
      <VStack spacing={7} align="center" maxW="820px" w="100%" textAlign="center">
        <Reveal variant="soft">
          <VStack spacing={5} align="center">
            {/* Брендовая плитка-иконка: стеклянная поверхность + iris-свечение. */}
            <Center
              boxSize="60px"
              borderRadius={borderRadius.lg}
              bg={CHAT_THEME.accentSoft}
              border={`1px solid ${colors.accent.subtleBorder}`}
              boxShadow={`${shadows.glassCard}, 0 0 40px ${CHAT_THEME.accentGlow}`}
            >
              <Icon as={FiZap} boxSize="26px" color={colors.blue[300]} />
            </Center>

            <VStack spacing={2.5}>
              <Eyebrow>GPTHub · рабочее пространство</Eyebrow>
              <Text
                as="h1"
                fontSize={{ base: '26px', md: '32px' }}
                fontWeight="800"
                letterSpacing="-0.02em"
                fontFamily={CHAT_FONT_FAMILY}
                sx={{
                  background: gradients.iridescent,
                  backgroundClip: 'text',
                  WebkitBackgroundClip: 'text',
                  WebkitTextFillColor: 'transparent',
                  color: 'transparent',
                }}
              >
                {personas.length ? 'Кем мне быть?' : 'Чем могу помочь?'}
              </Text>
              <Text color={CHAT_THEME.textSecondary} fontSize="14px" lineHeight="1.6" maxW="540px">
                {personas.length
                  ? `Выберите специализацию — она меняет не только тон, но и то, что агент замечает в файлах, поиске и данных. Совместить можно не больше ${MAX_PERSONAS}.`
                  : 'Опишите задачу — или приложите файл.'}
              </Text>
            </VStack>
          </VStack>
        </Reveal>

        {personas.length > 0 && (
          <Reveal
            className="stagger-children"
            as={Grid}
            templateColumns={{ base: '1fr', sm: 'repeat(2, 1fr)', lg: 'repeat(3, 1fr)' }}
            gap={3}
            w="100%"
          >
            {personas.map(({ id, label, hint }) => {
              const isOn = selected.includes(id);
              // Недоступные при достигнутом потолке гасим, но НЕ прячем: исчезающая
              // карточка читается как «личность пропала», а не «сначала сними другую».
              const muted = !isOn && atCap;
              return (
                <HStack
                  key={id}
                  as="button"
                  type="button"
                  onClick={() => toggle(id)}
                  aria-pressed={isOn}
                  disabled={muted}
                  className="gold-edge-hover"
                  align="flex-start"
                  spacing={3}
                  p={4}
                  {...GLASS_CARD_BASE}
                  borderRadius={borderRadius.md}
                  textAlign="left"
                  opacity={muted ? 0.4 : 1}
                  cursor={muted ? 'not-allowed' : 'pointer'}
                  borderColor={isOn ? colors.accent.subtleBorder : undefined}
                  bg={isOn ? CHAT_THEME.accentSoft : undefined}
                  _after={CARD_TOP_LINE}
                  _hover={muted ? {} : CARD_HOVER_STATE}
                  _focusVisible={{ boxShadow: `0 0 0 2px ${colors.border.focus}`, outline: 'none' }}
                >
                  <Center
                    boxSize="34px"
                    flexShrink={0}
                    borderRadius={borderRadius.sm}
                    bg={CHAT_THEME.accentSoft}
                    border={`1px solid ${colors.accent.subtleBorder}`}
                  >
                    <Icon as={PERSONA_ICONS[id] || FiUser} boxSize="15px" color={colors.blue[300]} />
                  </Center>
                  <Box minW="0" flex="1">
                    <HStack spacing={1.5} align="center">
                      <Text fontSize="13.5px" fontWeight="600" color={CHAT_THEME.textPrimary} noOfLines={1}>
                        {label}
                      </Text>
                      {isOn && <Icon as={FiCheck} boxSize="13px" color={colors.blue[300]} />}
                      {/* Первая выбранная задаёт тон и формат ответа связки. Без пометки
                          порядок кликов выглядел бы несущественным, а он решающий. */}
                      {isOn && selected.length > 1 && selected[0] === id && (
                        <Text fontSize="10.5px" color={CHAT_THEME.textTertiary}>ведущая</Text>
                      )}
                    </HStack>
                    <Text fontSize="12px" color={CHAT_THEME.textTertiary} lineHeight="1.5" noOfLines={2} mt={0.5}>
                      {hint || 'Специализация из реестра админки.'}
                    </Text>
                  </Box>
                </HStack>
              );
            })}
          </Reveal>
        )}

        {personas.length > 0 && (
          <Text
            fontSize="11.5px"
            color={CHAT_THEME.textTertiary}
            fontFamily={typography.fontFamily.mono}
            letterSpacing="0.02em"
          >
            {selected.length
              ? `Выбрано ${selected.length} из ${MAX_PERSONAS} — сменить можно в любой момент под полем ввода`
              : 'Можно не выбирать — тогда отвечает обычный ассистент'}
          </Text>
        )}

        {onboarding && !onboarding.dismissed && (
          <ChatOnboarding
            steps={onboarding.steps}
            completedCount={onboarding.completedCount}
            total={onboarding.total}
            allDone={onboarding.allDone}
            onDismiss={onboarding.dismiss}
          />
        )}
      </VStack>
    </Center>
  );
}
