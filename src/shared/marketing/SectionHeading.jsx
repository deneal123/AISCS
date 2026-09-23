import React from "react";
import { Box, Text, VStack } from "@chakra-ui/react";
import { colors } from "@theme/tokens";
import { Reveal } from "@shared/motion/Reveal";
import Eyebrow from "@shared/brand/Eyebrow";

const SIZE_STYLE = { sm: "titleSm", md: "title", lg: "titleLg" };

/**
 * Заголовок секции: eyebrow (mono + линия) → title (h2) → copy → опц. action.
 * Сам оборачивается в <Reveal variant="deep">; классы `.section-header-*`
 * дают внутренний каскад (eyebrow→title→copy→action) на `.in`.
 * Общий примитив маркетинга (лендинг + /platform) — единый источник.
 *
 * `align` (default center — value-preserving), `size` (sm/md/lg — межсекционная
 * иерархия через textStyle-роли), `index` (нумерал-кикер перед eyebrow) — для
 * де-темплатизации; дефолты рендерят текущий вид без изменений.
 */
export default function SectionHeading({
  eyebrow,
  title,
  copy,
  action,
  index,
  align = "center",
  size = "md",
  maxWTitle,
  maxWCopy,
  mb = { base: 10, md: 14 },
}) {
  const alignItems = align === "center" ? "center" : "flex-start";
  const textAlign = align === "center" ? "center" : "left";
  // Узкая редакторская мера (эталон): левый заголовок держит короткую строку,
  // даже если секция во всю ширину — это и даёт «авторский» ритм. 640 вместо
  // 560 у эталона: русский набор шире, иначе строки рвутся и висят сироты.
  const titleWidth = maxWTitle ?? (align === "center" ? "720px" : "640px");
  const copyWidth = maxWCopy ?? (align === "center" ? "600px" : "520px");
  return (
    <Reveal variant="deep">
      <VStack spacing={3.5} align={alignItems} textAlign={textAlign} mb={mb}>
        {eyebrow && (
          <Box className="section-header-eyebrow">
            <Eyebrow>{index ? `${index} · ${eyebrow}` : eyebrow}</Eyebrow>
          </Box>
        )}
        <Text
          className="section-header-title"
          as="h2"
          textStyle={SIZE_STYLE[size] || "title"}
          color={colors.fg[1]}
          maxW={titleWidth}
          // Заголовок принимает строку, ReactNode или массив строк: каждый элемент
          // массива — <span>-блок, т.е. ОСОЗНАННЫЙ перенос строки (эталон), чтобы
          // узкая мера не рвала слова по дефису («чат-/ботом»).
          sx={{ "& > span": { display: "block" } }}
        >
          {Array.isArray(title)
            ? title.map((line) => (
                <Box as="span" key={line}>
                  {line}
                </Box>
              ))
            : title}
        </Text>
        {copy && (
          <Text
            className="section-header-copy"
            fontSize={{ base: "15px", md: "17px" }}
            color={colors.fg[3]}
            lineHeight="1.6"
            maxW={copyWidth}
          >
            {copy}
          </Text>
        )}
        {action && <Box className="section-header-action" pt={2}>{action}</Box>}
      </VStack>
    </Reveal>
  );
}
