import React from 'react';
import { Box, Button, Heading, Text, VStack } from '@chakra-ui/react';
import { useNavigate, useParams } from 'react-router-dom';
import { colors } from '@theme/tokens';
import { getLegalDocument } from '../documents';
import LegalDocument from '../components/LegalDocument';

// Публичная страница правового документа: /legal/:docId (offer | privacy).
// Доступна без авторизации — проверяющие ЮKassa и пользователи должны её видеть.
export default function LegalPage() {
  const { docId } = useParams();
  const navigate = useNavigate();
  const doc = getLegalDocument(docId);

  if (!doc) {
    return (
      <VStack spacing={4} py={16} textAlign="center">
        <Heading as="h1" size="md" color={colors.text.primary}>
          Документ не найден
        </Heading>
        <Text color={colors.text.secondary}>Запрошенный правовой документ отсутствует.</Text>
        <Button variant="outline" onClick={() => navigate('/')}>
          На главную
        </Button>
      </VStack>
    );
  }

  // Документ НЕ оборачиваем в Reveal: правовой текст обязан быть виден всегда,
  // без зависимости от scroll-анимации. Появление осталось только на шапке
  // документа (см. LegalDocument).
  return (
    <Box maxW="800px" mx="auto">
      <LegalDocument doc={doc} />
    </Box>
  );
}
