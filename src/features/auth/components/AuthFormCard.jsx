import React from "react";
import { Box, VStack } from "@chakra-ui/react";
import { borderRadius, shadows } from "@theme/tokens";
import { GLASS_SURFACE_STRONG } from "@theme/glass";

/**
 * AuthFormCard — стеклянная карточка формы авторизации (иридесцентное стекло
 * InCellCorp вместо плоской тёмной панели) + тонкая синяя линия у верхней кромки.
 */
const AuthFormCard = ({ children, maxW = "460px", ...rest }) => {
  return (
    <Box
      maxW={maxW}
      mx="auto"
      position="relative"
      w="full"
      _before={{
        content: '""',
        position: "absolute",
        top: "-1px",
        left: "22px",
        right: "22px",
        height: "2px",
        background: "linear-gradient(90deg, transparent, rgba(45, 91, 255, 0.7), transparent)",
        borderRadius: "999px",
        zIndex: 2,
      }}
      {...rest}
    >
      <Box
        {...GLASS_SURFACE_STRONG}
        // Карточка формы НЕ прозрачная: почти сплошная тёмная поверхность, чтобы
        // фон (линии/орб) не просвечивал и не мешал читать поля. Стеклянный бордер
        // + верхняя линия остаются ради бренд-стиля.
        background="rgba(13, 16, 30, 0.95)"
        position="relative"
        borderRadius={borderRadius["2xl"]}
        p={{ base: 5, sm: 6, md: 8 }}
        boxShadow={shadows.modal}
        zIndex={1}
      >
        <VStack spacing={{ base: 4, md: 6 }} position="relative" zIndex={1}>
          {children}
        </VStack>
      </Box>
    </Box>
  );
};

export default AuthFormCard;
