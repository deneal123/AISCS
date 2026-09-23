import React from 'react';
import { Box, Heading, ListItem, Text, UnorderedList, VStack } from '@chakra-ui/react';
import { colors } from '@theme/tokens';
import { Reveal } from '@shared/motion/Reveal';
import RequisitesCard from './RequisitesCard';

// Рендер структурированного правового документа (оферта, политика).
// Анимация появления — только на шапке: сам текст рендерится сразу, чтобы
// документ читался при любых условиях (см. комментарий в LegalPage).
function LegalDocument({ doc }) {
  if (!doc) return null;

  return (
    <VStack align="stretch" spacing={8}>
      <Reveal variant="soft" as={Box}>
        <Heading as="h1" size="lg" color={colors.text.primary} letterSpacing="-0.01em">
          {doc.title}
        </Heading>
        {doc.subtitle && (
          <Text mt={1} fontSize="md" color={colors.text.secondary}>
            {doc.subtitle}
          </Text>
        )}
        {doc.updatedAt && (
          <Text mt={2} fontSize="xs" color={colors.text.secondary}>
            Редакция от {doc.updatedAt}
          </Text>
        )}
      </Reveal>

      {doc.intro?.length > 0 && (
        <VStack align="stretch" spacing={3}>
          {doc.intro.map((para, i) => (
            <Text key={i} fontSize="sm" color={colors.text.secondary} lineHeight="1.8">
              {para}
            </Text>
          ))}
        </VStack>
      )}

      {doc.sections?.map((section, idx) => (
        <Box as="section" key={idx}>
          <Heading as="h2" size="sm" color={colors.text.primary} mb={3}>
            {section.title}
          </Heading>

          {section.paragraphs?.map((para, i) => (
            <Text key={i} fontSize="sm" color={colors.text.secondary} lineHeight="1.8" mb={2}>
              {para}
            </Text>
          ))}

          {section.list && (
            <UnorderedList spacing={2} pl={1} color={colors.text.secondary}>
              {section.list.map((item, i) => (
                <ListItem key={i} fontSize="sm" lineHeight="1.8">
                  {item}
                </ListItem>
              ))}
            </UnorderedList>
          )}

          {section.requisites && (
            <Box mt={2}>
              <RequisitesCard />
            </Box>
          )}
        </Box>
      ))}
    </VStack>
  );
}

export default LegalDocument;
