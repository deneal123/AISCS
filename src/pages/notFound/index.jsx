import React from "react";
import { Box, Heading, HStack, Text, VStack } from "@chakra-ui/react";
import { APP_ROUTES } from "@app/router";
import { colors, gradients } from "@theme/tokens";
import Eyebrow from "@shared/brand/Eyebrow";
import ActionLink from "@shared/controls/ActionLink";

function NotFoundPage() {
  return (
    <Box
      minH={{ base: "60vh", md: "68vh" }}
      display="flex"
      alignItems="center"
      justifyContent="center"
      px={4}
      py={16}
    >
      <VStack spacing={6} textAlign="center" maxW="520px">
        <Eyebrow>Ошибка 404</Eyebrow>
        <Heading
          as="h1"
          fontSize={{ base: "96px", md: "132px" }}
          fontWeight="900"
          lineHeight="0.95"
          letterSpacing="-0.03em"
          sx={{
            background: gradients.iridescent,
            backgroundClip: "text",
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
            color: "transparent",
          }}
        >
          404
        </Heading>
        <VStack spacing={2.5}>
          <Heading as="h2" fontSize={{ base: "20px", md: "24px" }} fontWeight="700" color={colors.text.primary}>
            Такой страницы нет
          </Heading>
          <Text fontSize="15px" color={colors.text.secondary} lineHeight="1.6" maxW="440px">
            Возможно, ссылка устарела или страница была перемещена. Вернитесь на
            главную или откройте рабочее пространство.
          </Text>
        </VStack>
        <HStack spacing={3} pt={2} flexWrap="wrap" justify="center">
          <ActionLink to={APP_ROUTES.ROOT} variant="primary" size="md">
            На главную
          </ActionLink>
          <ActionLink to={APP_ROUTES.CHAT} variant="secondary" size="md">
            Открыть чат
          </ActionLink>
        </HStack>
      </VStack>
    </Box>
  );
}

export default NotFoundPage;
