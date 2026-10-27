import { useRef } from 'react';
import { AlertDialog, AlertDialogBody, AlertDialogContent, AlertDialogFooter, AlertDialogHeader,
  AlertDialogOverlay, Button } from '@chakra-ui/react';
import { colors } from '@theme/tokens';

export function PdfStartContentDialog({ isOpen, onClose, onConfirm, finalFocusRef }) {
  const cancel = useRef(null);
  return <AlertDialog isOpen={isOpen} onClose={onClose} leastDestructiveRef={cancel} finalFocusRef={finalFocusRef} motionPreset="none">
    <AlertDialogOverlay>
      <AlertDialogContent bg={colors.ink[900]} mx={3} maxH="85dvh">
        <AlertDialogHeader fontSize="16px">Создать новое содержание?</AlertDialogHeader>
        <AlertDialogBody overflowY="auto" fontSize="14px" color={colors.fg[2]}>
          Это не извлечение текста из PDF. Текущие исходники LaTeX будут заменены новой структурой
          для визуального редактора. Чтобы продолжить работу с существующим текстом, отмените
          создание и откройте исходник. ИИ не используется.
        </AlertDialogBody>
        <AlertDialogFooter gap={2} flexWrap="wrap">
          <Button ref={cancel} size="workbench" variant="workbenchSecondary" onClick={onClose}>Отмена</Button>
          <Button size="workbench" variant="workbenchPrimary" onClick={onConfirm}>Создать новое содержание</Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialogOverlay>
  </AlertDialog>;
}
