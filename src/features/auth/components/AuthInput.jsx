import React, { useState } from "react";
import { Box, FormControl, FormErrorMessage, FormLabel, Input, Icon } from "@chakra-ui/react";
import { colors, typography } from "@theme/tokens";
import { INPUT_BASE } from "@theme/glass";

/**
 * AuthInput — поле ввода форм авторизации на стеклянной системе InCellCorp.
 * База — INPUT_BASE (@theme/glass): translucent-заливка, iris-бордер, радиус sm,
 * лёгкий синий focus (без scale и тяжёлого glow). Красный — только для ошибок.
 * Сохраняет: левую иконку, FormLabel/autoComplete, error/helper, forward ref.
 */
const AuthInput = ({
  id,
  label,
  type = "text",
  value,
  onChange,
  placeholder,
  icon,
  isRequired = false,
  isInvalid = false,
  errorMessage,
  helperText,
  autoComplete,
  inputRef,
  ...rest
}) => {
  const [isFocused, setIsFocused] = useState(false);
  const iconColor = isInvalid
    ? colors.error
    : isFocused
      ? colors.blue[300]
      : colors.fg[4];

  return (
    <FormControl id={id} isRequired={isRequired} isInvalid={isInvalid}>
      <FormLabel fontSize="13px" fontWeight="500" color={colors.fg[3]} mb={2}>
        {label}
      </FormLabel>

      <Box position="relative">
        {icon && (
          <Box
            position="absolute"
            left="14px"
            top="50%"
            transform="translateY(-50%)"
            zIndex={2}
            pointerEvents="none"
          >
            <Icon as={icon} color={iconColor} w={5} h={5} transition="color 160ms ease" />
          </Box>
        )}

        <Input
          ref={inputRef}
          type={type}
          value={value}
          onChange={onChange}
          placeholder={placeholder}
          autoComplete={autoComplete}
          onFocus={() => setIsFocused(true)}
          onBlur={() => setIsFocused(false)}
          {...INPUT_BASE}
          pl={icon ? "44px" : "14px"}
          pr="14px"
          h="50px"
          fontSize={typography.body?.small || "15px"}
          borderColor={isInvalid ? colors.error : undefined}
          _hover={{ borderColor: isInvalid ? colors.error : colors.glass.borderHi }}
          _focusVisible={
            isInvalid
              ? {
                  borderColor: colors.error,
                  bg: colors.bg.inputStrong,
                  boxShadow: `0 0 0 2px ${colors.error}`,
                }
              : INPUT_BASE._focusVisible
          }
          {...rest}
        />
      </Box>

      {isInvalid && errorMessage && (
        <FormErrorMessage fontSize="13px" mt={1.5}>
          {errorMessage}
        </FormErrorMessage>
      )}

      {!isInvalid && helperText && (
        <Box fontSize="13px" color={colors.fg[4]} mt={1.5}>
          {helperText}
        </Box>
      )}
    </FormControl>
  );
};

export default AuthInput;
