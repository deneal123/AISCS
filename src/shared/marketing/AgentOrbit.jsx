import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Box, Icon, Text, keyframes } from "@chakra-ui/react";
import { FiZap } from "@shared/icons";
import { colors, motion as motionTokens } from "@theme/tokens";
import { useInView } from "@hooks/useInView";
import { prefersReducedMotion } from "@utils/motion";

const RING = 40; // радиус кольца в % контейнера
const CYCLE_MS = 2600;

const corePulse = keyframes`
  0%, 100% { transform: translate(-50%, -50%) scale(1); opacity: 0.5; }
  50% { transform: translate(-50%, -50%) scale(1.12); opacity: 0.85; }
`;
const nodeIn = keyframes`
  from { opacity: 0; transform: translate(-50%, -50%) scale(0.6); }
  to   { opacity: 1; transform: translate(-50%, -50%) scale(1); }
`;

// Позиции узлов по кольцу (старт сверху, по часовой).
function nodePos(i, n) {
  const a = (i / n) * 2 * Math.PI - Math.PI / 2;
  return { x: 50 + RING * Math.cos(a), y: 50 + RING * Math.sin(a) };
}

// Ломаное кольцо: радиус скачет от вершины к вершине — угловатый контур вместо
// гладкого круга (тот же язык, что у ломаного фона).
const JAGGED_RING = Array.from({ length: 22 }, (_, k) => {
  const a = (k / 22) * 2 * Math.PI - Math.PI / 2;
  const r = RING + (k % 2 ? 3.4 : -2.6) + (k % 3 === 0 ? 1.8 : 0) + (k % 5 === 0 ? -1.4 : 0);
  return `${(50 + r * Math.cos(a)).toFixed(2)},${(50 + r * Math.sin(a)).toFixed(2)}`;
}).join(" ");

// Коннектор ядро→узел с изломом посередине (перпендикулярный сдвиг).
function connectorPath(p, i) {
  const dx = p.x - 50;
  const dy = p.y - 50;
  const len = Math.hypot(dx, dy) || 1;
  const nx = -dy / len;
  const ny = dx / len;
  const k = (i % 2 ? 1 : -1) * (2.4 + (i % 3) * 1.5);
  const mx = 50 + dx * 0.55 + nx * k;
  const my = 50 + dy * 0.55 + ny * k;
  return `M 50 50 L ${mx.toFixed(2)} ${my.toFixed(2)} L ${p.x.toFixed(2)} ${p.y.toFixed(2)}`;
}

/**
 * Интерактивная «орбита оркестрации»: ядро-оркестратор в центре, вокруг —
 * узлы (агенты/возможности) своим цветом; коннекторы, авто-цикл подсветки,
 * активация по наведению. items: [{ key, icon, title, description, color }].
 * Собрана из существующих ресурсов (colors.agents, motion, useInView).
 */
export default function AgentOrbit({ items = [] }) {
  // once=false: авто-цикл орбиты должен ЗАМИРАТЬ, когда секция уходит с экрана.
  // С one-shot-наблюдателем интервал раз в 2.6 с перерисовывал SVG до конца
  // сессии, даже когда орбита давно за пределами вьюпорта.
  const [ref, inView] = useInView(0.3, '0px', false);
  // `active` — единственный источник правды о показанной фиче. Наведение НЕ
  // заводит отдельное состояние: оно сразу делает узел активным и лишь ставит
  // авто-цикл на паузу. Поэтому после увода курсора ничего не «отщёлкивает»
  // назад — цикл продолжается с той фичи, на которую смотрели.
  const [active, setActive] = useState(0);
  const [paused, setPaused] = useState(false);
  const reduced = prefersReducedMotion();
  const n = items.length;

  useEffect(() => {
    if (!inView || reduced || paused || n === 0) return undefined;
    const id = setInterval(() => setActive((a) => (a + 1) % n), CYCLE_MS);
    return () => clearInterval(id);
  }, [inView, reduced, paused, n]);

  const current = active;
  const cur = items[current] || items[0];
  const positions = useMemo(() => items.map((_, i) => nodePos(i, n)), [items, n]);
  const onEnter = useCallback((i) => {
    setActive(i);
    setPaused(true);
  }, []);
  const onLeave = useCallback(() => setPaused(false), []);

  if (n === 0) return null;

  return (
    <Box ref={ref} display="flex" flexDirection={{ base: "column", lg: "row" }} alignItems="center" gap={{ base: 8, lg: 10 }}>
      {/* Радиальная схема */}
      <Box
        position="relative"
        flexShrink={0}
        w={{ base: "300px", md: "330px", lg: "350px" }}
        h={{ base: "300px", md: "330px", lg: "350px" }}
      >
        {/* Ломаное кольцо, констелляция, ломаные коннекторы и бегущие импульсы */}
        <Box as="svg" viewBox="0 0 100 100" position="absolute" inset={0} w="100%" h="100%" pointerEvents="none">
          {/* Ломаное кольцо орбиты — вращается (не гладкий круг: тот же угловатый
              язык, что у фона) */}
          <polygon
            className={reduced ? undefined : "orbit-ring"}
            points={JAGGED_RING}
            fill="none"
            stroke={colors.glass.border}
            strokeWidth="0.35"
            strokeDasharray="1.6 2.2"
          />
          {/* Констелляция: узлы соединены в многоугольник — видна структура */}
          <polygon
            className={reduced ? undefined : "orbit-ring-rev"}
            points={positions.map((p) => `${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(" ")}
            fill="none"
            stroke={colors.glass.border}
            strokeWidth="0.22"
            strokeOpacity="0.55"
          />
          {positions.map((p, i) => {
            const on = i === current;
            const d = connectorPath(p, i);
            return (
              <g key={items[i].key || items[i].title}>
                <path
                  id={`orbit-conn-${i}`}
                  d={d}
                  fill="none"
                  stroke={items[i].color}
                  strokeWidth={on ? 0.9 : 0.35}
                  strokeOpacity={on ? 0.95 : 0.2}
                  // Активный коннектор — бегущий пунктир: данные текут в оркестратор.
                  strokeDasharray={on ? "2.5 2.5" : undefined}
                  className={on && !reduced ? "orbit-flow" : undefined}
                  style={{ transition: "stroke-opacity 400ms, stroke-width 400ms" }}
                />
                {/* Импульс-сигнал бежит по коннектору от узла к ядру */}
                {!reduced && (
                  <circle r={on ? 1.5 : 0.85} fill={items[i].color} opacity={on ? 0.95 : 0.28}>
                    <animateMotion
                      dur={on ? "1.4s" : "2.8s"}
                      repeatCount="indefinite"
                      keyPoints="1;0"
                      keyTimes="0;1"
                      calcMode="linear"
                    >
                      <mpath href={`#orbit-conn-${i}`} />
                    </animateMotion>
                  </circle>
                )}
              </g>
            );
          })}
        </Box>

        {/* Свечение активного (аура цвета агента — заметно плотнее) */}
        <Box
          aria-hidden
          position="absolute"
          left="50%"
          top="50%"
          w="78%"
          h="78%"
          borderRadius="full"
          transform="translate(-50%, -50%)"
          bg={`radial-gradient(circle, ${cur.color}30, ${cur.color}10 45%, transparent 72%)`}
          transition="background 500ms"
          pointerEvents="none"
        />

        {/* Ядро-оркестратор */}
        <Box position="absolute" left="50%" top="50%" transform="translate(-50%, -50%)" textAlign="center" zIndex={2}>
          <Box
            aria-hidden
            position="absolute"
            left="50%"
            top="50%"
            boxSize="120%"
            borderRadius="full"
            border={`1px solid ${colors.accent.subtleBorder}`}
            animation={reduced ? undefined : `${corePulse} 3.4s ${motionTokens.easeInOut} infinite`}
          />
          {/* Второе кольцо в цвете активного агента — ядро «отзывается» на узел */}
          <Box
            aria-hidden
            position="absolute"
            left="50%"
            top="50%"
            boxSize="152%"
            borderRadius="full"
            border={`1px solid ${cur.color}40`}
            transition="border-color 500ms"
            animation={reduced ? undefined : `${corePulse} 4.6s ${motionTokens.easeInOut} infinite`}
          />
          <Box
            boxSize={{ base: "78px", md: "92px" }}
            borderRadius="full"
            bg={colors.glass.bg}
            border={`1px solid ${colors.glass.borderHi}`}
            backdropFilter="blur(6px)"
            display="flex"
            alignItems="center"
            justifyContent="center"
            boxShadow={`0 0 46px ${colors.accent.glow}, 0 0 70px ${cur.color}33`}
            transition="box-shadow 500ms"
          >
            <Icon as={FiZap} boxSize={{ base: "28px", md: "34px" }} color={colors.blue[300]} />
          </Box>
        </Box>

        {/* Узлы */}
        {items.map((item, i) => {
          const p = positions[i];
          const on = i === current;
          const NodeIcon = item.icon;
          return (
            <Box
              key={item.key || item.title}
              as="button"
              type="button"
              aria-label={item.title}
              onMouseEnter={() => onEnter(i)}
              onMouseLeave={onLeave}
              onFocus={() => onEnter(i)}
              onBlur={onLeave}
              position="absolute"
              left={`${p.x}%`}
              top={`${p.y}%`}
              transform="translate(-50%, -50%)"
              zIndex={on ? 3 : 1}
              animation={reduced ? undefined : `${nodeIn} 420ms ${motionTokens.easeOut} both`}
              style={{ animationDelay: `${i * 70}ms` }}
            >
              <Box position="relative" display="flex" alignItems="center" justifyContent="center">
                {/* Импульс-кольцо активного узла — расходится, как сигнал */}
                {on && !reduced && (
                  <Box
                    aria-hidden
                    className="orbit-node-pulse"
                    position="absolute"
                    boxSize={{ base: "54px", md: "62px" }}
                    borderRadius="full"
                    border={`1.5px solid ${item.color}`}
                    pointerEvents="none"
                  />
                )}
                <Box
                  boxSize={on ? { base: "54px", md: "62px" } : { base: "48px", md: "52px" }}
                  borderRadius="full"
                  display="flex"
                  alignItems="center"
                  justifyContent="center"
                  bg={on ? `${item.color}2E` : colors.glass.bg}
                  border={`1.5px solid ${on ? item.color : `${item.color}66`}`}
                  // Узлы светятся всегда (слабо), активный — сильно: орбита
                  // перестаёт читаться как набор пустых кружков.
                  boxShadow={on ? `0 0 30px ${item.color}99` : `0 0 14px ${item.color}33`}
                  transition={`all 320ms ${motionTokens.easeOut}`}
                >
                  <Icon as={NodeIcon} boxSize={on ? "26px" : "21px"} color={on ? item.color : colors.fg[2]} transition="all 320ms" />
                </Box>
              </Box>
            </Box>
          );
        })}
      </Box>

      {/* Подпись активного */}
      <Box flex="1" minW={{ lg: "280px" }} textAlign={{ base: "center", lg: "left" }}>
        <Text textStyle="dataLabel" color={cur.color} mb={2}>
          {String(current + 1).padStart(2, "0")} / {String(n).padStart(2, "0")}
        </Text>
        <Text as="h3" textStyle="titleSm" color={colors.fg[1]} mb={2} transition="color 300ms">
          {cur.title}
        </Text>
        <Text fontSize={{ base: "15px", md: "16px" }} color={colors.fg[3]} lineHeight="1.65" minH={{ lg: "80px" }}>
          {cur.description}
        </Text>
        {/* Точки-индикаторы */}
        <Box display="flex" gap={{ base: 0, md: 2 }} mt={5} justifyContent={{ base: "center", lg: "flex-start" }}>
          {items.map((item, i) => (
            <Box
              key={item.key || item.title}
              as="button"
              type="button"
              aria-label={`Показать: ${item.title}`}
              onMouseEnter={() => onEnter(i)}
              onFocus={() => onEnter(i)}
              onBlur={onLeave}
              h="48px"
              w={{ base: "48px", md: "32px" }}
              display="flex"
              alignItems="center"
              justifyContent="center"
              position="relative"
              _after={{
                content: '""',
                h: "4px",
                w: i === current ? "24px" : "10px",
                borderRadius: "full",
                bg: i === current ? item.color : colors.border.medium,
                transition: `all 320ms ${motionTokens.easeOut}`,
              }}
              _focusVisible={{
                outline: `2px solid ${colors.border.focus}`,
                outlineOffset: "2px",
                borderRadius: "full",
              }}
            />
          ))}
        </Box>
      </Box>
    </Box>
  );
}
