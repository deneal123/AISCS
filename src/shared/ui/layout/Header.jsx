import React, { useEffect } from "react";
import { Box, Flex, HStack, IconButton, Link, useDisclosure } from "@chakra-ui/react";
import { HamburgerIcon } from "@chakra-ui/icons";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { APP_ROUTES, isLandingRoute } from "@app/router";
import { FiCreditCard, FiMessageSquare, FiShield } from "@shared/icons";
import { useAuth } from "@app/providers";
import { borderRadius, colors, transitions, typography } from "@theme/tokens";
import { PROJECT_VERSION } from "@constants";
import { preloadRoute } from "@hooks/useRoutePreload";
import { useActiveSection } from "@hooks/useActiveSection";
import { LANDING_NAV } from "@/content/landing";
import { PROJECT_NAME } from "@constants";
import Logo from "@shared/ui/assets/common/Logo";
import MagneticButton from "@shared/controls/MagneticButton";
import { HEADER_THEME } from "./headerTheme";
import { useHeaderScroll } from "./useHeaderScroll";
import HeaderUserMenu from "./HeaderUserMenu";
import HeaderMobileMenu from "./HeaderMobileMenu";

// Базовые пункты для авторизованных; «Админ» добавляется ниже только админам.
const BASE_NAV = [
  { label: "Чат", to: APP_ROUTES.CHAT, icon: FiMessageSquare },
  { label: "Тарифы", to: APP_ROUTES.BILLING, icon: FiCreditCard },
];

const LANDING_SECTION_IDS = LANDING_NAV.links.map((l) => l.id);

// Токенизированные повторяющиеся рецепты шапки (было продублировано литералами).
const TRANSITION = `all ${transitions.default}`;
const FOCUS_RING = `0 0 0 2px ${colors.border.focus}`;
const HOVER_BG = colors.border.subtle;
const ACTIVE_UNDERLINE = `linear-gradient(90deg, transparent, ${colors.accent.base}, transparent)`;

const linkBaseStyles = {
  fontWeight: 500,
  fontSize: "13px",
  letterSpacing: "0",
  color: HEADER_THEME.muted,
  transition: TRANSITION,
};

function Header() {
  const { isAuthenticated, logout, user, isAdmin } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const isLanding = isLandingRoute(location.pathname);
  const { isOpen, onOpen, onClose } = useDisclosure();
  const scrolled = useHeaderScroll();
  const userLabel = user?.first_name || user?.email || "Профиль";
  const activeSection = useActiveSection(LANDING_SECTION_IDS, { enabled: isLanding });
  // Админам добавляем «Админ»; список идёт и в десктоп-навигацию, и в мобильное меню.
  const authedNav = isAdmin
    ? [...BASE_NAV, { label: "Админ", to: APP_ROUTES.ADMIN, icon: FiShield }]
    : BASE_NAV;

  const scrollToSection = (id) => (e) => {
    e.preventDefault();
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const renderAnchor = (link) => {
    const active = activeSection === link.id;
    return (
      <Box
        key={link.id}
        as="a"
        href={`#${link.id}`}
        onClick={scrollToSection(link.id)}
        aria-current={active ? "true" : undefined}
        position="relative"
        px={3}
        py={2}
        borderRadius={borderRadius.md}
        cursor="pointer"
        {...linkBaseStyles}
        color={active ? colors.text.primary : HEADER_THEME.muted}
        _hover={{ color: colors.text.primary, bg: HOVER_BG }}
        _focusVisible={{ boxShadow: FOCUS_RING, outline: "none" }}
      >
        {link.label}
        {active && (
          <Box position="absolute" bottom="-2px" left={0} right={0} mx="auto" w="70%" h="2px" borderRadius="full"
            bg={ACTIVE_UNDERLINE} />
        )}
      </Box>
    );
  };

  useEffect(() => {
    onClose();
  }, [location.pathname, onClose]);



  return (
    <>
      {/* Шаблон Nav эталона: full-bleed, 61px, px 16/28, чёрная база + blur 20. */}
      <Flex
        as="header"
        position="sticky"
        top={0}
        zIndex={100}
        align="center"
        gap="18px"
        h="var(--app-header-h)"
        px={{ base: "16px", md: "28px" }}
        py="12px"
        borderBottom="1px solid"
        borderColor={scrolled ? HEADER_THEME.border : HEADER_THEME.borderSoft}
        bg={scrolled ? HEADER_THEME.bgScrolled : HEADER_THEME.bg}
        backdropFilter={scrolled ? "blur(24px)" : "blur(20px)"}
        transition={TRANSITION}
      >
        {/* Бренд — компактная одностроч. марка эталона (22px знак + 15px/700). */}
        <Link
          as={NavLink}
          to="/"
          display="inline-flex"
          alignItems="center"
          gap="10px"
          color={colors.fg[1]}
          fontSize="15px"
          fontWeight={700}
          whiteSpace="nowrap"
          aria-label={`${PROJECT_NAME} — на главную`}
          _hover={{ textDecoration: "none" }}
          _focusVisible={{ boxShadow: FOCUS_RING, outline: "none", borderRadius: borderRadius.sm }}
        >
          <Logo boxSize="22px" />
          <Box as="span">{PROJECT_NAME}</Box>
        </Link>

        {isLanding && (
          <Box
            as="span"
            display={{ base: "none", md: "inline-flex" }}
            px="6px"
            py="2px"
            border={`1px solid ${colors.border.subtle}`}
            borderRadius="4px"
            bg={colors.surface.tint1}
            color={colors.fg[4]}
            fontFamily={typography.fontFamily.mono}
            fontSize="10.5px"
            fontWeight={500}
            letterSpacing="0.02em"
            aria-hidden
          >
            v{PROJECT_VERSION}
          </Box>
        )}

        {/* Дивайдер во всю высоту шапки — как в эталоне. */}
        <Box w="1px" alignSelf="stretch" bg={colors.border.subtle} display={{ base: "none", lg: "block" }} />

        {isLanding && (
          <HStack as="nav" aria-label="Разделы страницы" spacing={1} display={{ base: "none", lg: "flex" }}>
            {LANDING_NAV.links.map(renderAnchor)}
            <Box
              as={NavLink}
              to={APP_ROUTES.PLATFORM}
              px={3}
              py={2}
              borderRadius={borderRadius.sm}
              {...linkBaseStyles}
              _hover={{ color: colors.text.primary, bg: HOVER_BG }}
              _focusVisible={{ boxShadow: FOCUS_RING, outline: "none" }}
            >
              Платформа
            </Box>
            <Box
              as={NavLink}
              to={APP_ROUTES.PRICING}
              px={3}
              py={2}
              borderRadius={borderRadius.sm}
              {...linkBaseStyles}
              _hover={{ color: colors.text.primary, bg: HOVER_BG }}
              _focusVisible={{ boxShadow: FOCUS_RING, outline: "none" }}
            >
              Тарифы
            </Box>
          </HStack>
        )}

        {/* Spacer */}
        <Box flex={1} />

        <Flex align="center" gap={{ base: 2, lg: 4 }}>
          {isLanding && !isAuthenticated && (
                  <Box
                    as={NavLink}
                    to={APP_ROUTES.PLATFORM}
                    display={{ base: "none", lg: "inline-flex" }}
                    alignItems="center"
                    gap="7px"
                    pl="8px"
                    pr="10px"
                    py="5px"
                    border={`1px solid ${colors.border.subtle}`}
                    borderRadius="full"
                    bg={colors.surface.tint1}
                    color={colors.fg[2]}
                    fontSize="12px"
                    whiteSpace="nowrap"
                    transition={TRANSITION}
                    _hover={{ borderColor: colors.border.light, color: colors.text.primary }}
                    _focusVisible={{ boxShadow: FOCUS_RING, outline: "none" }}
                  >
                    <Box as="span" w="6px" h="6px" flexShrink={0} borderRadius="full"
                      bg={colors.agents.web_search}
                      animation="pulse-green 2.8s cubic-bezier(0.4,0,0.6,1) infinite" />
                    <Box as="span">Все агенты онлайн</Box>
                  </Box>
                )}

                {isAuthenticated ? (
                  <HeaderUserMenu
                    userLabel={userLabel}
                    user={user}
                    navigate={navigate}
                    logout={logout}
                    navItems={authedNav}
                  />
                ) : (
                  <>
                    <HStack spacing={2} display={{ base: "none", lg: "flex" }}>
                      <MagneticButton
                        as={NavLink}
                        to={APP_ROUTES.LOGIN}
                        variant="secondary"
                        size="sm"
                        minH="36px"
                        px="14px"
                        onMouseEnter={() => preloadRoute(APP_ROUTES.LOGIN)}
                      >
                        Войти
                      </MagneticButton>
                      <MagneticButton
                        as={NavLink}
                        to={APP_ROUTES.SIGNUP}
                        variant="primary"
                        size="sm"
                        minH="36px"
                        px="14px"
                        onMouseEnter={() => preloadRoute(APP_ROUTES.SIGNUP)}
                      >
                        Начать
                      </MagneticButton>
                    </HStack>
                    {/* Планшет (md–lg): полноценная навигация уходит в бургер, но
                        главный CTA держим на виду — иначе центр шапки пустой. */}
                    <MagneticButton
                      as={NavLink}
                      to={APP_ROUTES.SIGNUP}
                      variant="primary"
                      size="sm"
                      minH="36px"
                      px="14px"
                      display={{ base: "none", md: "inline-flex", lg: "none" }}
                      onMouseEnter={() => preloadRoute(APP_ROUTES.SIGNUP)}
                    >
                      Начать
                    </MagneticButton>
                  </>
                )}

          {/* Бургер 44×44 с бордером — как в эталоне. Показываем только там, где
              он несёт СВОЁ содержимое: гостю (навигация + вход/регистрация) и на
              лендинге (якоря секций). У авторизованного на внутренних страницах
              бургер дублировал меню аккаунта — рядом стояли две кнопки-меню. */}
          <Box
            display={
              !isAuthenticated || isLanding
                ? { base: "block", lg: "none" }
                : "none"
            }
            transition={`transform ${transitions.default}`}
            _active={{ transform: "scale(0.95)" }}
          >
            <IconButton
              icon={<HamburgerIcon />}
              variant="ghost"
              onClick={onOpen}
              aria-label="Открыть меню"
              aria-haspopup="dialog"
              aria-expanded={isOpen}
              w="44px"
              h="44px"
              minW="44px"
              borderRadius={borderRadius.sm}
              border={`1px solid ${colors.border.subtle}`}
              bg="rgba(255,255,255,0.02)"
              color={HEADER_THEME.text}
              _hover={{ bg: HOVER_BG, borderColor: colors.border.blue }}
            />
          </Box>
        </Flex>
      </Flex>

      <HeaderMobileMenu
        isOpen={isOpen}
        onClose={onClose}
        navigate={navigate}
        isAuthenticated={isAuthenticated}
        isLanding={isLanding}
        landingLinks={LANDING_NAV.links}
      />
    </>
  );
}

export default Header;
