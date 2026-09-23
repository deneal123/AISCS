import React from 'react';
import { Text } from '@chakra-ui/react';
import { colors, typography } from '@theme/tokens';

// Тёплый янтарный тон дизайн-системы = «сырая / experimental» функция.
// НЕ красный: красный зарезервирован строго под ошибки/danger.
const AMBER = colors.spectral.amber; // #FFC56E

/**
 * BetaTag — крошечный маркер «бета»/сырой функции чата (веб-поиск, deep research,
 * генерация изображений и презентаций). Приглушённая янтарная mono-таблетка,
 * читается как beta. Рендерится инлайн-span'ом, поэтому безопасно кладётся
 * внутрь кнопок и пунктов меню. Переиспользуется в ChatEmptyState и
 * ComposerModeSelector — единый визуальный язык маркера.
 */
export default function BetaTag(props) {
  return (
    <Text
      as="span"
      display="inline-flex"
      alignItems="center"
      flexShrink={0}
      px="5px"
      py="1px"
      borderRadius="full"
      fontSize="9.5px"
      fontWeight="700"
      lineHeight="1.5"
      letterSpacing="0.08em"
      textTransform="uppercase"
      fontFamily={typography.fontFamily.mono}
      color={AMBER}
      bg="rgba(255, 197, 110, 0.10)"
      border="1px solid rgba(255, 197, 110, 0.28)"
      {...props}
    >
      бета
    </Text>
  );
}
