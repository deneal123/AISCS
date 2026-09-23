import React, { useState } from "react";
import {
  Box,
  FormControl,
  FormErrorMessage,
  FormLabel,
  HStack,
  Input,
  Icon,
  IconButton,
  Text,
} from "@chakra-ui/react";
import { ViewIcon, ViewOffIcon, LockIcon, WarningTwoIcon } from "@chakra-ui/icons";
import { colors, typography } from "@theme/tokens";
import { INPUT_BASE } from "@theme/glass";

/**
 * PasswordInput — поле пароля на стеклянной системе InCellCorp (INPUT_BASE) с
 * иконкой замка и переключателем видимости. Красный — только для ошибок;
 * без scale и тяжёлого focus-glow. Forward ref для autofocus/фокуса на ошибку.
 */
const PasswordInput = ({
  id,
  label,
  value,
  onChange,
  placeholder,
  isRequired = false,
  isInvalid = false,
  errorMessage,
  helperText,
  autoComplete,
  inputRef,
  ...rest
}) => {
  const [isFocused, setIsFocused] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [capsLock, setCapsLock] = useState(false);

  const togglePasswordVisibility = () => setShowPassword((v) => !v);
  const syncCapsLock = (e) => {
    if (typeof e.getModifierState === "function") {
      setCapsLock(e.getModifierState("CapsLock"));
    }
  };
  const lockColor = isInvalid
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
        {/* Lock icon */}
        <Box
          position="absolute"
          left="14px"
          top="50%"
          transform="translateY(-50%)"
          zIndex={2}
          pointerEvents="none"
        >
          <Icon as={LockIcon} color={lockColor} w={5} h={5} transition="color 160ms ease" />
        </Box>

        {/* Toggle visibility button */}
        <Box position="absolute" right="8px" top="50%" transform="translateY(-50%)" zIndex={2}>
          <IconButton
            size="sm"
            minW="44px"
            minH="44px"
            variant="ghost"
            icon={<Icon as={showPassword ? ViewOffIcon : ViewIcon} w={5} h={5} />}
            onClick={togglePasswordVisibility}
            aria-label={showPassword ? "Скрыть пароль" : "Показать пароль"}
            color={colors.fg[4]}
            _hover={{ bg: "transparent", color: colors.blue[300] }}
            _active={{ bg: "transparent", color: colors.blue[600] }}
          />
        </Box>

        <Input
          ref={inputRef}
          type={showPassword ? "text" : "password"}
          value={value}
          onChange={onChange}
          placeholder={placeholder}
          autoComplete={autoComplete}
          onFocus={(e) => {
            setIsFocused(true);
            syncCapsLock(e);
          }}
          onBlur={() => {
            setIsFocused(false);
            setCapsLock(false);
          }}
          onKeyUp={syncCapsLock}
          onKeyDown={syncCapsLock}
          {...INPUT_BASE}
          pl="44px"
          pr="44px"
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

      {capsLock && (
        <HStack spacing={1.5} mt={1.5} color={colors.warning} aria-live="polite">
          <Icon as={WarningTwoIcon} boxSize="12px" />
          <Text fontSize="12px">Включён Caps Lock</Text>
        </HStack>
      )}

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

export default PasswordInput;
