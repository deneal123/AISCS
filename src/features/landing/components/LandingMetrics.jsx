import React from "react";
import { Box, Flex, Grid, Link, Text } from "@chakra-ui/react";
import { Link as RouterLink } from "react-router-dom";
import { colors } from "@theme/tokens";
import { Reveal } from "@shared/motion/Reveal";
import { LANDING_METRICS } from "@/content/landing";
import MetricCounter from "@shared/marketing/MetricCounter";
import { Section, PageShell } from "@shared/marketing/primitives";

const DIVIDER = "1px solid rgba(102, 133, 255, 0.24)";
const { items, context, action, label } = LANDING_METRICS;

function ActionLink() {
  return (
    <Link
      as={RouterLink}
      to={action.to}
      display="inline-flex"
      alignItems="center"
      gap={1.5}
      minH="38px"
      px={3.5}
      border={`1px solid ${colors.border.subtle}`}
      borderRadius="10px"
      bg={colors.surface.tint1}
      color={colors.blue[300]}
      fontSize="12px"
      fontWeight="700"
      whiteSpace="nowrap"
      _hover={{ borderColor: colors.border.light, color: colors.fg[1], textDecoration: "none" }}
    >
      {action.label}
      <Box as="span" className="link-arrow" aria-hidden>↗</Box>
    </Link>
  );
}

/**
 * Полоса доверия (band, не глава): слева контекст-текст, по центру метрики с
 * вертикальными дивайдерами, справа ссылка. Композиция ProofStrip эталона —
 * поэтому без большого заголовка и без сквозного номера.
 */
export default function LandingMetrics() {
  const [stats, setStats] = React.useState(null);
  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { request } = await import("@api/request");
        const res = await request({ method: "get", url: "/api/analytics/public" });
        if (!cancelled && res) setStats(res);
      } catch {
        /* сеть недоступна — показываем статичные метрики */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Живая активность проекта (обезличенная): пользователи, обработано токенов,
  // визиты. До загрузки/при ошибке — статичные метрики из контента.
  const liveItems = stats
    ? [
        { value: Number(stats.users || 0), suffix: "", label: "пользователей на платформе" },
        { value: Number(stats.tokens_spent || 0), suffix: "", label: "токенов обработано" },
        { value: Number(stats.visits || 0), suffix: "", label: "визитов на сайт" },
        { value: 5, suffix: "", label: "LLM-провайдеров с фейловером" },
      ]
    : items;

  return (
    <Section
      id="metrics"
      compact
      aria-label={label}
      bg="rgba(0, 0, 0, 0.36)"
      borderTop="1px solid rgba(102, 133, 255, 0.14)"
      borderBottom="1px solid rgba(102, 133, 255, 0.14)"
    >
      <PageShell>
        <Reveal className="stagger-children">
          {/* Десктоп: один горизонтальный ряд */}
          <Flex display={{ base: "none", lg: "flex" }} align="stretch" w="100%" minW={0}>
            <Text
              flex="0 0 230px"
              pr={7}
              borderRight={DIVIDER}
              color={colors.fg[3]}
              fontSize="12px"
              lineHeight="1.55"
            >
              {context}
            </Text>
            <Grid flex="1 1 auto" minW={0} templateColumns="repeat(4, minmax(0, 1fr))">
              {liveItems.map((m, i) => (
                <Box
                  key={m.label}
                  minW={0}
                  px={7}
                  borderRight={i === liveItems.length - 1 ? undefined : DIVIDER}
                >
                  <MetricCounter value={m.value} suffix={m.suffix} label={m.label} align="left" />
                </Box>
              ))}
            </Grid>
            <Flex flex="0 0 230px" pl={7} borderLeft={DIVIDER} align="center" justify="flex-end">
              <ActionLink />
            </Flex>
          </Flex>

          {/* Планшет/мобила: контекст сверху, метрики 2×2, ссылка снизу */}
          <Box display={{ base: "block", lg: "none" }}>
            <Text color={colors.fg[3]} fontSize="13px" lineHeight="1.55" mb={6} maxW="520px">
              {context}
            </Text>
            <Grid templateColumns="repeat(2, minmax(0, 1fr))" gap={{ base: 8, md: 10 }}>
              {liveItems.map((m) => (
                <MetricCounter key={m.label} value={m.value} suffix={m.suffix} label={m.label} align="left" />
              ))}
            </Grid>
            <Box mt={7}>
              <ActionLink />
            </Box>
          </Box>
        </Reveal>
      </PageShell>
    </Section>
  );
}
