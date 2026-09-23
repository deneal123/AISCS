import React from "react";
import { Text, VStack } from "@chakra-ui/react";
import Eyebrow from "@shared/brand/Eyebrow";
import { AUTH_BRAND_LABEL, AUTH_THEME } from "../constants";

/**
 * Шапка формы авторизации: DS-Eyebrow (mono + анимированная линия) + `h1`
 * (единственный h1 страницы) + подзаголовок. Чистый одиночный локап вместо
 * прежнего «AI»-чип + иконка-в-рамке — согласовано с лендингом.
 */
function AuthPageHeader({ title, description }) {
  return (
    <VStack align="stretch" spacing={2}>
      <Eyebrow>{AUTH_BRAND_LABEL}</Eyebrow>
      <Text
        as="h1"
        fontSize={{ base: "26px", md: "30px" }}
        fontWeight="800"
        letterSpacing="-0.02em"
        lineHeight="1.15"
        color="white"
      >
        {title}
      </Text>
      <Text fontSize="sm" color={AUTH_THEME.mutedText} lineHeight="1.55">
        {description}
      </Text>
    </VStack>
  );
}

export default AuthPageHeader;
