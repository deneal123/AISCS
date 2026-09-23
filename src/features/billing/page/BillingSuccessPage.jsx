import { useEffect } from 'react';
import { Button, Center, Heading, Icon, Text, VStack } from '@chakra-ui/react';
import { FiCheckCircle } from '@shared/icons';
import { useNavigate } from 'react-router-dom';
import { colors, borderRadius } from '@theme/tokens';
import { GLASS_CARD_BASE, CARD_TOP_LINE } from '@theme/glass';
import { CHAT_THEME } from '../../chat/constants/theme';
import { GHOST_BUTTON_BLUE_SX } from '@theme/styles';
import { Reveal } from '@shared/motion/Reveal';
import Eyebrow from '@shared/brand/Eyebrow';
import { notifyBillingRefresh } from '../context/BillingContext';

/** Экран подтверждения оплаты: успех + возврат к биллингу. */
export default function BillingSuccessPage() {
  const navigate = useNavigate();

  useEffect(() => {
    // Платёж проведён — баланс мог измениться (webhook начислит кредиты).
    notifyBillingRefresh();
    const timer = setInterval(notifyBillingRefresh, 3000);
    const stop = setTimeout(() => clearInterval(timer), 15000);
    return () => {
      clearInterval(timer);
      clearTimeout(stop);
    };
  }, []);

  return (
    <Center flex="1" bg={CHAT_THEME.pageBg} px={6}>
      <Reveal variant="rise">
        <VStack
          spacing={4}
          textAlign="center"
          maxW="420px"
          w="100%"
          p={8}
          {...GLASS_CARD_BASE}
          _after={{ ...CARD_TOP_LINE, opacity: 1 }}
        >
          <Center
            boxSize="56px"
            borderRadius={borderRadius.lg}
            bg={colors.successSoft}
            border={`1px solid ${colors.successBorder}`}
          >
            <Icon as={FiCheckCircle} boxSize="28px" color={colors.success} />
          </Center>
          <Eyebrow>Платёж</Eyebrow>
          <Heading as="h1" size="md" color={CHAT_THEME.textPrimary}>
            Оплата обработана
          </Heading>
          <Text color={CHAT_THEME.textSecondary} fontSize="14px" lineHeight="1.6">
            Баланс обновится в течение нескольких секунд после подтверждения платежа.
          </Text>
          <Button mt={1} onClick={() => navigate('/billing')} {...GHOST_BUTTON_BLUE_SX}>
            Вернуться к биллингу
          </Button>
        </VStack>
      </Reveal>
    </Center>
  );
}
