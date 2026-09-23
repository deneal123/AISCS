import { HStack, Icon, Text } from '@chakra-ui/react';
import { FiZap } from '@shared/icons';
import { useNavigate } from 'react-router-dom';
import { CHAT_THEME } from '../../chat/constants/theme';
import { colors } from '@theme/tokens';
import { formatCredits } from '../lib/credits';

export default function CreditsPill({ total }) {
  const navigate = useNavigate();
  if (total == null) return null;
  const empty = Number(total) <= 0;
  return (
    <HStack
      as="button"
      onClick={() => navigate('/billing')}
      spacing={1.5}
      px={3}
      h="32px"
      borderRadius="full"
      bg={empty ? colors.errorSoft : colors.border.default}
      border={`1px solid ${empty ? colors.errorBorder : CHAT_THEME.panelBorder}`}
      _hover={{ bg: CHAT_THEME.panelHover }}
      _focusVisible={{ boxShadow: `0 0 0 2px ${colors.border.focus}`, outline: 'none' }}
      aria-label={empty ? 'Кредиты закончились — пополнить' : 'Баланс кредитов, открыть биллинг'}
      title={empty ? 'Кредиты закончились — пополнить' : 'Баланс кредитов'}
    >
      <Icon as={FiZap} boxSize={3.5} color={empty ? colors.error : colors.brand.primary} />
      <Text fontSize="12.5px" fontWeight="600" color={empty ? colors.error : CHAT_THEME.textPrimary}>
        {empty ? 'Пополнить' : formatCredits(total)}
      </Text>
    </HStack>
  );
}
