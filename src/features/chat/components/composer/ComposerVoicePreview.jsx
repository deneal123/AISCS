import React from 'react';
import { Box, HStack, Icon, IconButton, Text } from '@chakra-ui/react';
import { FiEdit2, FiMic, FiX } from '@shared/icons';
import { colors, borderRadius, typography } from '@theme/tokens';
import { CHAT_THEME } from '../../constants/theme';

/**
 * Аккуратное превью распознанного голосового над полем ввода. Два ряда:
 * заголовок (микрофон + метка + действия) и сам транскрипт, ограниченный по
 * высоте (2 строки, дальше — многоточие). Отправить как есть — кнопкой Send;
 * дописать в поле — карандаш; убрать — крестик. Компонент рендерится ВНУТРИ
 * композера (в той же maxW-колонке), поэтому идеально выровнен с вводом при
 * любом состоянии сайдбара. Приглушённый стеклянный акцент, не сплошная заливка.
 */
function ComposerVoicePreview({ text, onDiscard, onEdit }) {
  if (!text) return null;
  return (
    <Box
      mb={2}
      px={3}
      py={2.5}
      borderRadius={borderRadius.md}
      bg={colors.accent.softest}
      border="1px solid"
      borderColor={colors.accent.hoverSoft}
    >
      <HStack spacing={2} mb={1.5} align="center">
        <Icon as={FiMic} boxSize="13px" color={colors.blue[300]} flexShrink={0} />
        <Text
          flex="1"
          minW={0}
          fontSize="9.5px"
          fontWeight="700"
          letterSpacing="0.07em"
          textTransform="uppercase"
          color={colors.blue[300]}
          fontFamily={typography.fontFamily.mono}
        >
          Распознанный голос
        </Text>
        <IconButton
          aria-label="Дописать в поле ввода"
          title="Дописать в поле ввода"
          icon={<FiEdit2 />}
          size="xs"
          variant="ghost"
          minW="24px"
          h="24px"
          color={CHAT_THEME.textTertiary}
          _hover={{ color: CHAT_THEME.textPrimary, bg: CHAT_THEME.panelHover }}
          onClick={onEdit}
        />
        <IconButton
          aria-label="Убрать голосовое"
          title="Убрать"
          icon={<FiX />}
          size="xs"
          variant="ghost"
          minW="24px"
          h="24px"
          color={CHAT_THEME.textTertiary}
          _hover={{ color: CHAT_THEME.textPrimary, bg: CHAT_THEME.panelHover }}
          onClick={onDiscard}
        />
      </HStack>
      <Text fontSize="13px" color={CHAT_THEME.textPrimary} lineHeight="1.5" noOfLines={2} pl="21px">
        {text}
      </Text>
    </Box>
  );
}

export default ComposerVoicePreview;
