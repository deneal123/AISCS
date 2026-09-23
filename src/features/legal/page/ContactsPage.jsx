import React from 'react';
import { Box, Heading, HStack, Icon, Link, Text, VStack } from '@chakra-ui/react';
import { FiMail, FiMapPin, FiPhone } from '@shared/icons';
import { MERCHANT, MERCHANT_OKVED } from '@shared/config/merchant';
import { colors, borderRadius } from '@theme/tokens';
import { GLASS_SURFACE } from '@theme/glass';
import { Reveal } from '@shared/motion/Reveal';
import RequisitesCard from '../components/RequisitesCard';

// Публичная страница «Контакты и реквизиты» — обязательна для приёма платежей.
const CONTACTS = [
  { icon: FiMail, label: 'E-mail', value: MERCHANT.email, href: `mailto:${MERCHANT.email}` },
  { icon: FiPhone, label: 'Телефон', value: MERCHANT.phone, href: `tel:${MERCHANT.phone.replace(/[^+\d]/g, '')}` },
  { icon: FiMapPin, label: 'Адрес', value: MERCHANT.address },
];

export default function ContactsPage() {
  return (
    <Box maxW="800px" mx="auto">
      <VStack align="stretch" spacing={8}>
        <Reveal variant="soft" as={Box}>
          <Heading as="h1" size="lg" color={colors.text.primary} letterSpacing="-0.01em">
            Контакты и реквизиты
          </Heading>
          <Text mt={2} fontSize="sm" color={colors.text.secondary}>
            Свяжитесь с нами по любым вопросам, связанным с работой сервиса {MERCHANT.serviceName},
            оплатой и возвратом средств.
          </Text>
        </Reveal>

        <Reveal className="stagger-children" as={VStack} align="stretch" spacing={0}
          borderTop={`1px solid ${colors.border.subtle}`}>
          {CONTACTS.map((c) => (
            <HStack
              key={c.label}
              role="group"
              spacing={4}
              align="center"
              py={4}
              borderBottom={`1px solid ${colors.border.subtle}`}
              transition="border-color 200ms"
              _hover={{ borderBottomColor: colors.border.light }}
            >
              <Box
                boxSize="40px"
                flexShrink={0}
                borderRadius="10px"
                display="flex"
                alignItems="center"
                justifyContent="center"
                bg={colors.surface.tint1}
                border={`1px solid ${colors.border.subtle}`}
                transition="border-color 200ms"
                _groupHover={{ borderColor: colors.border.light }}
              >
                <Icon as={c.icon} boxSize={5} color={colors.brand.primary} />
              </Box>
              <Box>
                <Text fontSize="11px" textTransform="uppercase" letterSpacing="0.06em" color={colors.text.tertiary}>
                  {c.label}
                </Text>
                {c.href ? (
                  <Link href={c.href} fontSize="15px" color={colors.text.primary} fontWeight="500">
                    {c.value}
                  </Link>
                ) : (
                  <Text fontSize="15px" color={colors.text.primary} fontWeight="500">
                    {c.value}
                  </Text>
                )}
              </Box>
            </HStack>
          ))}
        </Reveal>

        <Reveal variant="soft" as={Box}>
          <Heading as="h2" size="sm" color={colors.text.primary} mb={3}>
            Реквизиты
          </Heading>
          <RequisitesCard />
        </Reveal>

        <Reveal variant="soft" as={Box}>
          <Heading as="h2" size="sm" color={colors.text.primary} mb={3}>
            Виды деятельности (ОКВЭД)
          </Heading>
          <Box p={6} {...GLASS_SURFACE} borderRadius={borderRadius.lg}>
            <VStack align="stretch" spacing={3}>
              {MERCHANT_OKVED.map((item) => (
                <HStack key={item.code} align="flex-start" spacing={3}>
                  <Text
                    flexShrink={0}
                    minW="56px"
                    fontSize="sm"
                    fontWeight="600"
                    color={colors.brand.primary}
                    fontFamily="mono"
                  >
                    {item.code}
                  </Text>
                  <Text fontSize="sm" color={colors.text.secondary} lineHeight="1.6">
                    {item.title}
                  </Text>
                </HStack>
              ))}
            </VStack>
          </Box>
        </Reveal>
      </VStack>
    </Box>
  );
}
