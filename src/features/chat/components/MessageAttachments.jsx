import React from 'react';
import { Button, HStack, Icon, Text, VStack, Wrap, WrapItem } from '@chakra-ui/react';
import { FiCode, FiDatabase, FiFileText, FiFolder, FiImage, FiMic } from '@shared/icons';
import { colors, borderRadius } from '@theme/tokens';
import { CHAT_THEME } from '../constants/theme';

// Зеркалит ICON_BY_TYPE из composer/ComposerAttachments — общий словарь иконок вложений.
const ICON_BY_TYPE = {
  image: FiImage,
  audio: FiMic,
  code: FiCode,
  csv: FiDatabase,
  json: FiDatabase,
};

/**
 * Read-only чипы вложений в пузыре пользователя (без кнопки удаления) — тот же
 * стиль, что и превью в композере, но презентационный: только иконка + имя файла.
 */
function MessageAttachments({ attachments, onOpenWork }) {
  const list = Array.isArray(attachments) ? attachments : [];
  if (list.length === 0) {
    return null;
  }

  return (
    <VStack mb={2} spacing={1.5} align="start">
      <Wrap spacing={2}>
        {list.map((item, index) => (
          <WrapItem key={`${item.filename || 'att'}_${index}`}>
            <HStack px={2.5} py={1} bg={CHAT_THEME.accentSoft} border={`1px solid ${colors.accent.subtleBorder}`} borderRadius={borderRadius.full} spacing={2}>
              <Icon as={ICON_BY_TYPE[item.file_type] || FiFileText} color={colors.blue[300]} boxSize={4} />
              <Text fontSize="xs" color={colors.blue[100]} noOfLines={1} maxW="200px">
                {item.filename}
              </Text>
            </HStack>
          </WrapItem>
        ))}
      </Wrap>
      {onOpenWork && (
        <Button
          size="xs"
          variant="ghost"
          leftIcon={<FiFolder />}
          onClick={onOpenWork}
          aria-label={`Открыть работу с вложениями: ${list.length}`}
          color={colors.blue[200]}
          _hover={{ bg: colors.accent.hoverSoft, color: 'white' }}
        >
          Открыть работу
        </Button>
      )}
    </VStack>
  );
}

export default MessageAttachments;
