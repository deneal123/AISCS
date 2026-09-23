import React from "react";
import {
  Box,
  Button,
  Divider,
  Drawer,
  DrawerBody,
  DrawerCloseButton,
  DrawerContent,
  DrawerHeader,
  DrawerOverlay,
  VStack,
} from "@chakra-ui/react";
import { borderRadius, colors, transitions } from "@theme/tokens";
import { DRAWER_OVERLAY_PROPS, DRAWER_CONTENT_BG } from "@theme/drawer";
import { APP_ROUTES } from "@app/router";
import { HEADER_THEME } from "./headerTheme";
import BrandMark from "./BrandMark";

/** Мобильное меню-дровер: якоря лендинга / навигация + гостевые CTA / профиль+выход. */
export default function HeaderMobileMenu({
  isOpen,
  onClose,
  navigate,
  isAuthenticated,
  isLanding = false,
  landingLinks = [],
}) {
  const go = (to) => {
    navigate(to);
    onClose();
  };
  const scrollTo = (id) => {
    onClose();
    // Дать дроверу закрыться, затем плавно проскроллить к секции.
    setTimeout(() => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" }), 60);
  };

  const rowStyles = {
    display: "flex",
    alignItems: "center",
    gap: 3,
    px: 4,
    py: 3,
    borderRadius: borderRadius.md,
    fontWeight: 500,
    w: "full",
    textAlign: "left",
    cursor: "pointer",
    color: HEADER_THEME.muted,
    _hover: { bg: colors.border.subtle, color: HEADER_THEME.text },
    _focusVisible: { boxShadow: `0 0 0 2px ${colors.border.blue}`, outline: "none" },
  };

  return (
    <Drawer
      isOpen={isOpen}
      placement="right"
      onClose={onClose}
      size="xs"
      blockScrollOnMount={false}
      closeOnOverlayClick
      closeOnEsc
    >
      <DrawerOverlay {...DRAWER_OVERLAY_PROPS} sx={{ transition: "none !important", animation: "none !important" }} />
      <DrawerContent
        bg={DRAWER_CONTENT_BG}
        borderLeft={`1px solid ${HEADER_THEME.border}`}
        sx={{ transition: `transform ${transitions.default} !important`, animation: "none !important" }}
      >
        <DrawerCloseButton aria-label="Закрыть меню" color={HEADER_THEME.muted} _hover={{ color: HEADER_THEME.text }} />
        <DrawerHeader borderBottomWidth="1px" borderColor={colors.border.subtle}>
          <BrandMark size="sm" />
        </DrawerHeader>

        <DrawerBody py={6}>
          <VStack spacing={2} align="stretch">
            {/* Якоря лендинга */}
            {isLanding &&
              landingLinks.map((link) => (
                <Box key={link.id} as="button" onClick={() => scrollTo(link.id)} {...rowStyles}>
                  {link.label}
                </Box>
              ))}

            {/* Страницы «Платформа» и «Тарифы» (route) — на лендинге, рядом с якорями */}
            {isLanding && (
              <Box as="button" onClick={() => go(APP_ROUTES.PLATFORM)} {...rowStyles}>
                Платформа
              </Box>
            )}
            {isLanding && (
              <Box as="button" onClick={() => go(APP_ROUTES.PRICING)} {...rowStyles}>
                Тарифы
              </Box>
            )}

            {/* Разделы приложения, профиль и выход авторизованному здесь НЕ
                показываем: они живут в меню аккаунта (HeaderUserMenu), которое
                доступно на всех ширинах. Иначе получался дубль — две кнопки-меню
                рядом и одни и те же пункты в обеих. */}

            {/* Гость: CTA на вход/регистрацию */}
            {!isAuthenticated && (
              <VStack spacing={2.5} align="stretch" pt={isLanding ? 4 : 0}>
                {isLanding && <Divider borderColor={colors.border.subtle} mb={1.5} />}
                <Button variant="primary" size="md" onClick={() => go(APP_ROUTES.SIGNUP)}>
                  Начать бесплатно
                </Button>
                <Button variant="secondary" size="md" onClick={() => go(APP_ROUTES.LOGIN)}>
                  Войти
                </Button>
              </VStack>
            )}

          </VStack>
        </DrawerBody>
      </DrawerContent>
    </Drawer>
  );
}
