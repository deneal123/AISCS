import React from "react";
import { Box, HStack, VStack, Text, Icon, VisuallyHidden, usePrefersReducedMotion } from "@chakra-ui/react";
import { CheckCircleIcon, WarningIcon } from "@chakra-ui/icons";
import { keyframes } from "@emotion/react";
import { colors, borderRadius } from "@theme/tokens";

const pulse = keyframes`
  0%, 100% { opacity: 0.6; }
  50% { opacity: 1; }
`;

const shimmer = keyframes`
  0% { background-position: -200% 0; }
  100% { background-position: 200% 0; }
`;

const fadeInDown = keyframes`
  from { opacity: 0; transform: translateY(-10px); }
  to { opacity: 1; transform: translateY(0); }
`;

const popIn = keyframes`
  from { opacity: 0; transform: scale(0); }
  to { opacity: 1; transform: scale(1); }
`;

/**
 * PasswordStrength - индикатор силы пароля с проверками
 * Анимированные требования с иконками
 */
// rgba-тинт от токена colors.success (#10b981) — чтобы зелёные акценты индикатора
// следовали за токеном, а не жили литералами rgba(16,185,129,…).
const successTint = (alpha) => {
  const hex = colors.success.replace("#", "");
  const r = parseInt(hex.slice(0, 2), 16);
  const g = parseInt(hex.slice(2, 4), 16);
  const b = parseInt(hex.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
};

const PasswordStrength = ({ password }) => {
  const prefersReducedMotion = usePrefersReducedMotion();

  const checks = [
    {
      id: "length",
      label: "Минимум 8 символов",
      test: (pwd) => pwd.length >= 8,
    },
    {
      id: "letter",
      label: "Хотя бы одна буква",
      test: (pwd) => /[A-Za-zА-Яа-я]/.test(pwd),
    },
    {
      id: "digit",
      label: "Хотя бы одна цифра",
      test: (pwd) => /\d/.test(pwd),
    },
  ];

  const passedChecks = checks.filter((check) => check.test(password));
  const strengthPercentage = (passedChecks.length / checks.length) * 100;

  // Цвет прогресса в зависимости от силы
  const getProgressColor = () => {
    if (passedChecks.length === 0) return colors.text.tertiary;
    if (passedChecks.length === 1) return colors.error; // red — status token
    if (passedChecks.length === 2) return colors.warning; // orange — status token
    return colors.success; // green — status token (not neon)
  };

  const getStrengthLabel = () => {
    if (passedChecks.length <= 1) return "Слабый";
    if (passedChecks.length === 2) return "Средний";
    return "Сильный";
  };

  const progressColor = getProgressColor();

  return (
    <Box
      animation={prefersReducedMotion ? undefined : `${fadeInDown} 0.3s ease-out`}
      mt={3}
      p={4}
      bg={colors.bg.panel}
      borderRadius={borderRadius.lg}
      border={`1px solid ${colors.border.subtle}`}
      position="relative"
      overflow="hidden"
      _before={{
        content: '""',
        position: "absolute",
        top: 0,
        left: 0,
        width: "3px",
        height: "100%",
        background: progressColor,
        opacity: 0.8,
        transition: "background 0.3s ease",
      }}
    >
      {/* Живая озвучка для screen-reader: сила + сколько требований выполнено.
          aria-live=polite → анонс на паузах ввода, а не на каждый символ; сам
          индикатор до этого был чисто визуальным (цвет + иконки). */}
      <VisuallyHidden role="status" aria-live="polite">
        {`Надёжность пароля: ${getStrengthLabel().toLowerCase()}. Выполнено требований: ${passedChecks.length} из ${checks.length}.`}
      </VisuallyHidden>

      {/* Background glow based on strength */}
      <Box
        position="absolute"
        top="-50%"
        right="-30%"
        width="150px"
        height="150px"
        background={`radial-gradient(circle, ${progressColor}20 0%, transparent 70%)`}
        filter="blur(40px)"
        transition="all 0.3s ease"
        pointerEvents="none"
      />

      {/* Progress bar section (визуальная — озвучка выше через role=status) */}
      <Box mb={4} position="relative" zIndex={1} aria-hidden="true">
        <HStack justify="space-between" mb={2}>
          <Text fontSize="xs" color={colors.text.secondary}>
            Сила пароля
          </Text>
          <HStack spacing={1}>
            <Box
              w={2}
              h={2}
              borderRadius="full"
              bg={progressColor}
              animation={
                passedChecks.length === 3 && !prefersReducedMotion
                  ? `${pulse} 1.5s ease-in-out infinite`
                  : "none"
              }
            />
            <Text fontSize="xs" color={progressColor} fontWeight="600" transition="color 0.3s ease">
              {getStrengthLabel()}
            </Text>
          </HStack>
        </HStack>

        {/* Animated progress bar */}
        <Box
          h="6px"
          borderRadius="full"
          bg={colors.border.default}
          overflow="hidden"
          position="relative"
        >
          <Box
            h="100%"
            w="100%"
            borderRadius="full"
            background={`linear-gradient(90deg, ${progressColor}, ${progressColor}CC)`}
            position="relative"
            transform={`scaleX(${strengthPercentage / 100})`}
            transition="transform 0.4s ease-out"
            style={{ transformOrigin: "left", willChange: "transform" }}
            _after={{
              content: '""',
              position: "absolute",
              inset: 0,
              background: "linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent)",
              backgroundSize: "200% 100%",
              animation: prefersReducedMotion ? "none" : `${shimmer} 2s linear infinite`,
            }}
          />
        </Box>
      </Box>

      {/* Requirements list */}
      <Box>
        <VStack align="stretch" spacing={2}>
          {checks.map((check) => {
            const passed = check.test(password);
            return (
              <Box key={check.id}>
                <HStack
                  spacing={3}
                  p={2}
                  borderRadius={borderRadius.md}
                  bg={passed ? successTint(0.08) : "transparent"}
                  border="1px solid"
                  borderColor={passed ? successTint(0.28) : "transparent"}
                  transition="all 0.2s ease"
                >
                  <Box
                    w={5}
                    h={5}
                    borderRadius="full"
                    bg={passed ? successTint(0.18) : colors.border.default}
                    display="flex"
                    alignItems="center"
                    justifyContent="center"
                    transition="all 0.2s ease"
                  >
                    <Icon
                      as={passed ? CheckCircleIcon : WarningIcon}
                      color={passed ? colors.success : colors.text.tertiary}
                      w={3}
                      h={3}
                      transition="color 0.2s"
                      aria-hidden="true"
                    />
                  </Box>
                  <Text
                    fontSize="xs"
                    color={passed ? colors.text.primary : colors.text.tertiary}
                    fontWeight={passed ? "500" : "400"}
                    transition="all 0.2s ease"
                  >
                    {check.label}
                    {/* Состояние требования для screen-reader (визуально — иконка+цвет). */}
                    <VisuallyHidden>{passed ? " — выполнено" : " — не выполнено"}</VisuallyHidden>
                  </Text>
                  {passed && (
                    <Box
                      ml="auto"
                      aria-hidden="true"
                      animation={prefersReducedMotion ? undefined : `${popIn} 0.2s ease-out`}
                    >
                      <Box
                        px={2}
                        py={0.5}
                        borderRadius="full"
                        bg={successTint(0.14)}
                        border={`1px solid ${successTint(0.28)}`}
                      >
                        <Text fontSize="10px" color={colors.success} fontWeight="600">
                          ✓
                        </Text>
                      </Box>
                    </Box>
                  )}
                </HStack>
              </Box>
            );
          })}
        </VStack>
      </Box>
    </Box>
  );
};

export default PasswordStrength;
