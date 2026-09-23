import React from 'react';
import { Button, HStack, Icon, IconButton, Text, VStack, Wrap, WrapItem } from '@chakra-ui/react';
import { FiCode, FiDatabase, FiFileText, FiFolder, FiImage, FiMic, FiX } from '@shared/icons';
import { colors, borderRadius } from '@theme/tokens';
import { CHAT_THEME } from '../../constants/theme';

const ICON_BY_TYPE = {
  image: FiImage,
  audio: FiMic,
  code: FiCode,
  csv: FiDatabase,
  json: FiDatabase,
};

function ComposerAttachments({ attachments, onRemove, onOpenWork }) {
  const list = Array.isArray(attachments) ? attachments : attachments ? [attachments] : [];
  if (list.length === 0) {
    return null;
  }

  return (
    <VStack mb={2} spacing={1.5} align="start">
      <Wrap spacing={2}>
        {list.map((item, index) => (
          <WrapItem key={`${item.file_id || item.filename || 'att'}_${index}`}>
            <HStack px={2.5} py={1} bg={CHAT_THEME.accentSoft} border={`1px solid ${colors.accent.subtleBorder}`} borderRadius={borderRadius.full} spacing={2}>
              <Icon as={ICON_BY_TYPE[item.file_type] || FiFileText} color={colors.blue[300]} boxSize={4} />
              <Text fontSize="xs" color={colors.blue[100]} noOfLines={1} maxW="180px">
                {item.filename} ({item.file_type})
              </Text>
              <IconButton
                aria-label={`Удалить вложение ${item.filename || index + 1}`}
                icon={<FiX />}
                size="xs"
                variant="ghost"
                color={CHAT_THEME.textTertiary}
                _hover={{ color: colors.iris[300], bg: colors.accent.subtle }}
                onClick={() => onRemove?.(index)}
              />
            </HStack>
          </WrapItem>
        ))}
      </Wrap>
      {onOpenWork && (
        <Button
          size="xs"
          variant="ghost"
          minW="auto"
          px={1.5}
          leftIcon={<FiFolder />}
          color={colors.blue[200]}
          _hover={{ bg: colors.accent.hoverSoft, color: 'white' }}
          onClick={onOpenWork}
          aria-label={`Открыть работу с вложениями: ${list.length}`}
        >
          Открыть работу
        </Button>
      )}
    </VStack>
  );
}

export default ComposerAttachments;
