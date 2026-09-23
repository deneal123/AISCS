import React from "react";
import {
  Avatar,
  Box,
  Button,
  Divider,
  HStack,
  Icon,
  Menu,
  MenuButton,
  MenuItem,
  MenuList,
  Portal,
  Stack,
  Text,
  VStack,
} from "@chakra-ui/react";
import { useLocation } from "react-router-dom";
import { ChevronRightIcon, TriangleDownIcon } from "@chakra-ui/icons";
import { FaSignOutAlt, FaUser } from "@shared/icons";
import { borderRadius, colors, shadows } from "@theme/tokens";
import { HEADER_THEME } from "./headerTheme";

const HEADER_MENU_MAX_WIDTH = "calc(100vw - 32px)";
const HEADER_MENU_STYLE = {
  width: "280px",
  minWidth: 0,
  maxWidth: HEADER_MENU_MAX_WIDTH,
};

/**
 * Аватар + меню аккаунта — ЕДИНЫЙ вход в навигацию для авторизованных.
 * Разделы приложения (Чат / Тарифы / Админ) живут здесь, а не отдельными
 * ссылками в шапке: раньше они дублировались и в шапке, и в бургере, а на
 * мобильном рядом стояли сразу две кнопки-меню (аватар и бургер).
 */
export default function HeaderUserMenu({ userLabel, user, navigate, logout, navItems = [] }) {
  const location = useLocation();
  // Открываем профиль, СОХРАНЯЯ текущий тред чата: если мы уже на /chat/:id —
  // добавляем ?profile=open к текущему пути, а не уводим на новый /chat.
  const openProfile = () => {
    const onChat = location.pathname.startsWith('/chat');
    navigate(`${onChat ? location.pathname : '/chat'}?profile=open`);
  };

  const menuItemStyles = {
    py: 3,
    px: 3,
    fontSize: "sm",
    borderRadius: borderRadius.md,
    bg: "transparent",
    color: HEADER_THEME.text,
    _hover: { bg: colors.surface.tint3 },
    _focus: { bg: colors.surface.tint3 },
  };

  return (
    <Menu>
      <MenuButton
        as={Button}
        variant="unstyled"
        size="sm"
        px={2}
        py={1}
        minH={{ base: "44px", md: "auto" }}
        minW={{ base: "44px", md: "auto" }}
        maxW={{ base: "44px", md: "300px" }}
        borderRadius={borderRadius.full}
        overflow="visible"
        aria-label="Меню аккаунта"
        _focusVisible={{ boxShadow: `0 0 0 2px ${colors.border.focus}`, outline: "none" }}
      >
        <HStack spacing={3} align="center" minW={0}>
          <Box
            position="relative"
            borderRadius="full"
            p="1.5px"
            bg="linear-gradient(135deg, rgba(45, 91, 255, 0.95), rgba(255, 255, 255, 0.4))"
          >
            <Avatar name={userLabel} size="xs" bg={colors.bg.menu} color={colors.text.primary} fontSize="10px" fontWeight="bold" />
            <Box position="absolute" bottom={0} right={0} w="8px" h="8px" borderRadius="full" bg={colors.accent.base} border="2px solid" borderColor="rgba(6, 6, 6, 1)" />
          </Box>

          <Stack
            spacing={0}
            align="flex-start"
            display={{ base: "none", md: "flex" }}
            minW={0}
            maxW="220px"
            overflow="hidden"
          >
            <Text fontSize="sm" fontWeight="500" color={HEADER_THEME.text} noOfLines={1} maxW="full">
              {user?.first_name || "Пользователь"}
            </Text>
            <Text
              fontSize="10px"
              color={HEADER_THEME.muted}
              letterSpacing="0.02em"
              noOfLines={1}
              maxW="full"
            >
              {user?.email || "user@local"}
            </Text>
          </Stack>

          <Icon as={TriangleDownIcon} fontSize="8px" color={HEADER_THEME.muted} display={{ base: "none", md: "block" }} />
        </HStack>
      </MenuButton>

      <Portal>
        <MenuList
          data-testid="header-user-menu"
          style={HEADER_MENU_STYLE}
          bg={colors.bg.menu}
          border="1px solid"
          borderColor={HEADER_THEME.border}
          borderRadius={borderRadius.lg}
          boxShadow={shadows.menu}
          py={0}
          px={0}
          overflow="hidden"
          zIndex={9999}
        >
          <Box position="absolute" top={0} left={0} right={0} h="2px" bg={`linear-gradient(90deg, transparent, ${colors.accent.base}, transparent)`} />

          <Box px={4} py={4} bg={colors.surface.tint1} borderBottom={`1px solid ${colors.surface.tint3}`}>
            <HStack spacing={3} minW={0}>
              <Avatar
                name={userLabel}
                size="md"
                bg={colors.bg.menu}
                color={colors.text.primary}
                fontWeight="bold"
                flexShrink={0}
              />
              <VStack align="start" spacing={0} minW={0} flex="1" overflow="hidden">
                <Text fontWeight="500" fontSize="sm" color={HEADER_THEME.text} noOfLines={1} maxW="full">
                  {user?.first_name || "Пользователь"}
                </Text>
                <Text fontSize="xs" color={HEADER_THEME.muted} noOfLines={1} maxW="full">
                  {user?.email}
                </Text>
              </VStack>
            </HStack>
          </Box>

          <Box p={2}>
            {/* Разделы приложения — единственное место, где они теперь живут. */}
            {navItems.map((item) => {
              const isActive =
                location.pathname === item.to || location.pathname.startsWith(`${item.to}/`);
              return (
                <MenuItem
                  key={item.to}
                  onClick={() => navigate(item.to)}
                  {...menuItemStyles}
                  bg={isActive ? colors.accent.subtle : "transparent"}
                  color={isActive ? HEADER_THEME.accent : HEADER_THEME.text}
                  icon={
                    <Icon
                      as={item.icon}
                      boxSize={4}
                      color={isActive ? HEADER_THEME.accent : HEADER_THEME.muted}
                    />
                  }
                  _hover={{ bg: isActive ? colors.accent.subtleHover : colors.surface.tint3 }}
                >
                  <HStack justify="space-between" w="full">
                    <Text>{item.label}</Text>
                    {isActive && (
                      <Box w="6px" h="6px" borderRadius="full" bg={HEADER_THEME.accent} aria-hidden />
                    )}
                  </HStack>
                </MenuItem>
              );
            })}

            {navItems.length > 0 && <Divider borderColor={colors.surface.tint3} my={2} />}

            <MenuItem
              onClick={openProfile}
              {...menuItemStyles}
              icon={<Icon as={FaUser} boxSize={4} color={HEADER_THEME.accent} />}
            >
              <HStack justify="space-between" w="full">
                <Text>Профиль</Text>
                <Icon as={ChevronRightIcon} boxSize={4} color={HEADER_THEME.muted} />
              </HStack>
            </MenuItem>

            <MenuItem
              onClick={logout}
              {...menuItemStyles}
              color={HEADER_THEME.accent}
              icon={<Icon as={FaSignOutAlt} boxSize={4} color={HEADER_THEME.accent} />}
              _hover={{ bg: colors.accent.soft }}
              _focus={{ bg: colors.accent.soft }}
            >
              Выйти
            </MenuItem>
          </Box>
        </MenuList>
      </Portal>
    </Menu>
  );
}
