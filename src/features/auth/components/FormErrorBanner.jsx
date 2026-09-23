import React, { forwardRef } from "react";
import { Box, HStack, Icon, Text, VStack } from "@chakra-ui/react";
import { FaExclamationCircle } from "@shared/icons";
import { borderRadius, colors } from "@theme/tokens";
import { AUTH_THEME } from "../constants";

/**
 * Баннер ошибки формы авторизации — единый для входа, регистрации и ввода кода.
 * Раньше эти три экрана несли три копии одной разметки ВМЕСТЕ с её a11y-контрактом
 * (role="alert", tabIndex={-1} для программного перевода фокуса, focus-ring), и
 * контракт легко было потерять при копировании.
 *
 * ref пробрасывается наружу: виджет переводит на баннер фокус после неудачной
 * отправки, чтобы скринридер прочитал ошибку.
 */
const FormErrorBanner = forwardRef(function FormErrorBanner({ title, message }, ref) {
  return (
    <Box
      ref={ref}
      tabIndex={-1}
      role="alert"
      aria-live="polite"
      p={3}
      bg={colors.errorSoft}
      border={`1px solid ${colors.errorBorder}`}
      borderRadius={borderRadius.lg}
      _focusVisible={{ outline: "none", boxShadow: `0 0 0 2px ${colors.error}` }}
    >
      <HStack spacing={2} align="start">
        <Icon as={FaExclamationCircle} color={colors.error} mt="2px" aria-hidden />
        <VStack align="start" spacing={0}>
          <Text fontSize="sm" fontWeight="500" color={colors.error}>
            {title}
          </Text>
          <Text fontSize="xs" color={AUTH_THEME.mutedText}>
            {message}
          </Text>
        </VStack>
      </HStack>
    </Box>
  );
});

export default FormErrorBanner;
