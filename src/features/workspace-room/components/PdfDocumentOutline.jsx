import { Button, Drawer, DrawerBody, DrawerCloseButton, DrawerContent, DrawerHeader, DrawerOverlay, Text, VStack } from '@chakra-ui/react';
import { colors } from '@theme/tokens';

export function PdfDocumentOutline({ isOpen, onClose, blocks, onNavigate, labels, finalFocusRef }) {
  return <Drawer isOpen={isOpen} onClose={onClose} placement="left" size="sm" finalFocusRef={finalFocusRef}>
    <DrawerOverlay /><DrawerContent bg={colors.ink[900]}>
      <DrawerCloseButton aria-label="Закрыть структуру документа" />
      <DrawerHeader>Структура документа</DrawerHeader>
      <DrawerBody overflowY="auto">
        <Text fontSize="12px" color={colors.fg[3]} mb={4}>Перейти к разделу или блоку. Содержимое и выделение не изменятся.</Text>
        <VStack align="stretch" spacing={1}>
          {blocks.map((block, index) => <Button key={block.block_id} variant="ghost" h="auto" minH="44px"
            py={2} justifyContent="flex-start" whiteSpace="normal" textAlign="left"
            onClick={() => { onNavigate(block.block_id); onClose(); }}>
            <Text fontSize="11px" color={colors.fg[4]} mr={3} flexShrink={0}>{index + 1}</Text>
            <Text fontSize="13px" noOfLines={2} fontWeight={block.kind === 'section' ? 600 : 400}>
              {block.title || block.text || labels[block.kind] || 'Блок документа'}
            </Text>
          </Button>)}
        </VStack>
      </DrawerBody>
    </DrawerContent>
  </Drawer>;
}
