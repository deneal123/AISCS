import React from "react";
import { Badge, Box, Grid, GridItem, HStack, Link, Text, VStack, Wrap, WrapItem } from "@chakra-ui/react";
import { Link as RouterLink, useLocation } from "react-router-dom";
import { FiArrowUpRight, FiArrowRight } from "@shared/icons";
import { PROJECT_VERSION } from "@constants";
import { colors } from "@theme/tokens";
import { GHOST_BADGE_BLUE_SX } from "@theme/styles";
import { MERCHANT } from "@shared/config/merchant";
import { APP_ROUTES, isAuthRoute } from "@app/router";
import { FOOTER_COPY } from "@/content/common";
import BrandMark from "./BrandMark";
import ActionLink from "@shared/controls/ActionLink";

// Якоря секций лендинга ведём через RouterLink (`to`), а не сырым `href`:
// сырая ссылка перезагружала всё приложение, а скролл к секции при этом не
// срабатывал — с любой не-лендинговой страницы «Как работает» / «Почему мы»
// открывали просто верх главной. Прокрутку к якорю делает ScrollToTop.
const COLS = [
  {
    title: "Продукт",
    links: [
      { label: "Возможности", to: "/#features" },
      { label: "Как работает", to: "/#how" },
      { label: "Почему мы", to: "/#why" },
      { label: "Платформа", to: APP_ROUTES.PLATFORM },
    ],
  },
  {
    title: "Использование",
    links: [
      { label: "Открыть чат", to: APP_ROUTES.CHAT },
      { label: "Тарифы и цены", to: APP_ROUTES.PRICING },
      { label: "Частые вопросы", to: "/#faq" },
      { label: "Контакты", to: APP_ROUTES.CONTACTS },
    ],
  },
  {
    title: "Правовое",
    links: [
      { label: "Публичная оферта", to: "/legal/offer" },
      { label: "Политика конфиденциальности", to: "/legal/privacy" },
      { label: "Согласие на обработку", to: "/legal/consent" },
    ],
  },
];

const linkSx = {
  className: "footer-link",
  fontSize: "13.5px",
  fontWeight: 500,
  color: colors.fg[3],
  _hover: { color: colors.fg[1], textDecoration: "none" },
  w: "fit-content",
};

function ColumnHeader({ children }) {
  return (
    <Text mb={1.5} color={colors.fg[2]} fontSize="11.5px" fontWeight={700} letterSpacing="0.06em" textTransform="uppercase">
      {children}
    </Text>
  );
}

function NavLink({ item }) {
  const props = item.to ? { as: RouterLink, to: item.to } : { href: item.href };
  return <Link {...props} {...linkSx}>{item.label}</Link>;
}

function Footer() {
  const location = useLocation();
  const isAuthPage = isAuthRoute(location.pathname);

  return (
    <Box as="footer" position="relative" w="100%" overflow="hidden" bg="transparent" borderTop={`1px solid ${colors.border.medium}`}>
      {/* Прозрачно (fins сквозь) + мягкое затемнение книзу для читаемости/контраста. */}
      <Box aria-hidden position="absolute" inset={0} bg="linear-gradient(180deg, rgba(3,4,9,0.4) 0%, rgba(3,4,9,0.78) 100%)" pointerEvents="none" />

      <Box position="relative" zIndex={1} maxW={isAuthPage ? "none" : "1520px"} mx="auto" px={isAuthPage ? 5 : { base: 5, md: 8, lg: 12 }} pt={{ base: 12, md: 14 }} pb={{ base: 6, md: 9 }}>
        <Grid
          templateColumns={{ base: "1fr", md: "1.4fr 1fr 1fr", lg: "1.5fr 1fr 1fr 1fr 1.4fr" }}
          gap={{ base: 10, md: 10, lg: 12 }}
          alignItems="start"
        >
          {/* Бренд + тэглайн + CTA + бейджи */}
          <GridItem colSpan={{ base: 1, md: 3, lg: 1 }}>
            <VStack align="flex-start" spacing={4} maxW="330px">
              <BrandMark />
              <Text fontSize="13px" color={colors.fg[3]} lineHeight="1.65">
                {FOOTER_COPY.tagline}
              </Text>
              <HStack spacing={2.5} pt={1}>
                <ActionLink to="/signup" variant="primary" size="sm" rightIcon={<FiArrowRight />}>
                  Начать бесплатно
                </ActionLink>
                <ActionLink to={APP_ROUTES.CHAT} variant="secondary" size="sm">
                  Открыть чат
                </ActionLink>
              </HStack>
              <HStack spacing={2} pt={1}>
                <Badge px={2.5} py={1} borderRadius="full" bg={colors.surface.tint2} border={`1px solid ${colors.border.medium}`} color={colors.fg[3]} fontWeight={600} textTransform="none" fontSize="11px">
                  v{PROJECT_VERSION}
                </Badge>
                <Badge px={2.5} py={1} borderRadius="full" {...GHOST_BADGE_BLUE_SX} border={`1px solid ${colors.accent.subtleBorder}`} fontWeight={600} textTransform="none" fontSize="11px">
                  {FOOTER_COPY.status.online}
                </Badge>
              </HStack>
            </VStack>
          </GridItem>

          {/* Колонки ссылок */}
          {COLS.map((col) => (
            <GridItem key={col.title}>
              <Box display="grid" alignContent="start" gap={2.5}>
                <ColumnHeader>{col.title}</ColumnHeader>
                {col.links.map((l) => <NavLink key={l.label} item={l} />)}
              </Box>
            </GridItem>
          ))}

          {/* Карточка «Сведения» — лёгкая, у правого края */}
          <GridItem>
            <Box p="14px" border={`1px solid ${colors.border.faint}`} borderRadius="12px" bg={colors.surface.tint1} display="grid" alignContent="start" gap={2.5}>
              <ColumnHeader>Сведения</ColumnHeader>
              <Text color={colors.fg[4]} fontSize="12.5px" lineHeight="1.5">
                Реквизиты подтверждены владельцем и публикуются открыто — без регистрации и передачи персональных данных.
              </Text>
              <Link as={RouterLink} to={APP_ROUTES.CONTACTS} display="inline-flex" alignItems="center" gap={1} fontSize="13.5px" color={colors.fg[3]} _hover={{ color: colors.fg[1], textDecoration: "none" }} pt={1}>
                Открыть контакты и реквизиты <Box as={FiArrowUpRight} />
              </Link>
            </Box>
          </GridItem>
        </Grid>

        {/* Нижняя строка */}
        <HStack justify="space-between" align="center" flexWrap="wrap" gap={4} mt={{ base: 8, md: 11 }} pt={5} borderTop={`1px solid ${colors.border.faint}`}>
          <Text fontSize="12px" color={colors.fg[4]}>
            © 2026 {FOOTER_COPY.company} Все права защищены.
          </Text>
          <Wrap spacing={{ base: "8px 16px", md: "20px" }} align="center">
            <WrapItem><Link href={`mailto:${MERCHANT.email}`} {...linkSx} fontSize="12px">{MERCHANT.email}</Link></WrapItem>
            <WrapItem><Link href={`tel:${MERCHANT.phone.replace(/[^\d+]/g, "")}`} {...linkSx} fontSize="12px">{MERCHANT.phone}</Link></WrapItem>
            <WrapItem><Link as={RouterLink} to={APP_ROUTES.CONTACTS} {...linkSx} fontSize="12px">Реквизиты</Link></WrapItem>
          </Wrap>
        </HStack>
      </Box>
    </Box>
  );
}

export default Footer;
