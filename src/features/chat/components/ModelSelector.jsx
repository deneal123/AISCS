import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Box,
  Button,
  Flex,
  HStack,
  Icon,
  Input,
  Menu,
  MenuButton,
  MenuItem,
  MenuList,
  Portal,
  Text,
  VStack,
} from "@chakra-ui/react";
import { FiCheck, FiChevronDown, FiEye, FiHeadphones, FiImage, FiPaperclip, FiSearch, FiTool } from "@shared/icons";
import { borderRadius, chat, colors, typography } from "@theme/tokens";
import { useResponsive } from "@hooks/useResponsive";
import { AUTO_MODE_LABEL, parseModelMeta, resolveModelTriggerLabel, sortModelsByProvider } from "../utils/modelSelector";

const CAP_ICON = { vision: FiEye, audio: FiHeadphones, files: FiPaperclip, image_out: FiImage, tools: FiTool };
// tools — критично: только такие модели МОГУТ сами позвать инструмент (напр. поиск по
// базе знаний). Остальные получают то же самое, но подмешанным в контекст автоматически.
const CAP_LABEL = { vision: "vision", audio: "audio", files: "files", image_out: "image", tools: "инструменты" };
// Рендерим не весь каталог (300+ моделей) — иначе меню лагает на открытии и
// прокрутке. Показываем первые N, остальное отсекаем поиском.
const MAX_RENDERED = 60;

function formatContext(n) {
  if (!n || n <= 0) return "";
  if (n >= 1000000) return `${(n / 1000000).toFixed(n % 1000000 ? 1 : 0)}M`;
  return `${Math.round(n / 1000)}K`;
}

function ModelSelector({ selectedModel, availableModels, catalog, onChange, size = "default", placement }) {
  const { isMobile } = useResponsive();
  const isAuto = !selectedModel;
  const label = resolveModelTriggerLabel(selectedModel);
  const isCompact = size === "compact";
  const [query, setQuery] = useState("");
  const searchRef = useRef(null);

  // Chakra Menu при смене состава MenuItem (фильтрация по вводу) уводит DOM-фокус
  // на пункт списка → поле поиска теряло фокус после КАЖДОЙ буквы (юзер жаловался).
  // Возвращаем фокус на поле после ре-рендера фильтра (rAF — уже после фокус-
  // менеджмента меню), курсор в конец. Гейт по activeElement — без лишних дёрганий.
  useEffect(() => {
    if (!query) return undefined;
    const id = requestAnimationFrame(() => {
      const el = searchRef.current;
      if (el && document.activeElement !== el) {
        el.focus();
        const len = el.value.length;
        try { el.setSelectionRange(len, len); } catch { /* noop */ }
      }
    });
    return () => cancelAnimationFrame(id);
  }, [query]);

  const models = useMemo(() => sortModelsByProvider(availableModels), [availableModels]);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return models;
    return models.filter((m) => {
      const meta = parseModelMeta(m);
      return (
        m.toLowerCase().includes(q) ||
        (meta.providerLabel || "").toLowerCase().includes(q) ||
        (meta.label || "").toLowerCase().includes(q)
      );
    });
  }, [models, query]);

  const shown = filtered.slice(0, MAX_RENDERED);
  const hiddenCount = filtered.length - shown.length;

  const renderItem = (modelId) => {
    const isSelected = selectedModel === modelId;
    const meta = parseModelMeta(modelId);
    const info = catalog ? catalog[modelId] : null;
    const ctx = info ? formatContext(info.context_window) : "";
    // Окно не подтверждено провайдером (proxy-модели) → показываем «~», а не как
    // реальное значение (жалоба «у всех 33K»).
    const ctxEstimated = !!info?.context_estimated;
    // Тир дороговизны: 0 эконом · 1 стандарт · 2 дорого. Флагаем крайние —
    // предупреждаем о дорогих (жалоба: pro слила все кредиты).
    const tier = info?.cost_tier;
    const caps = info && Array.isArray(info.capabilities) ? info.capabilities : [];
    const hasMeta = !!ctx || caps.length > 0 || tier === 0 || tier === 2;
    return (
      <MenuItem
        key={modelId}
        onClick={() => onChange(modelId)}
        bg={isSelected ? chat.modelSelector.itemSelectedBg : "transparent"}
        color={isSelected ? chat.modelSelector.activeText : colors.text.primary}
        _hover={{ bg: chat.modelSelector.itemHover }}
      >
        <VStack align="stretch" spacing={0.5} w="100%">
          <Flex justify="space-between" w="100%" gap={3} align="center">
            <HStack minW={0} spacing={2}>
              {meta.providerLabel && (
                <Box
                  as="span"
                  flexShrink={0}
                  fontSize="9.5px"
                  fontWeight="700"
                  letterSpacing="0.02em"
                  textTransform="uppercase"
                  px={1.5}
                  py="1px"
                  borderRadius="full"
                  color={colors.blue[300]}
                  bg={colors.accent.subtle}
                  border={`1px solid ${colors.accent.subtleBorder}`}
                  fontFamily={typography.fontFamily.mono}
                >
                  {meta.providerLabel}
                </Box>
              )}
              <Text noOfLines={1}>{meta.label}</Text>
            </HStack>
            {isSelected && <Icon as={FiCheck} flexShrink={0} />}
          </Flex>
          {hasMeta && (
            <HStack spacing={2} color={colors.text.tertiary} pl="1px">
              {ctx && (
                <Text
                  fontSize="10px"
                  fontFamily={typography.fontFamily.mono}
                  title={ctxEstimated ? "Окно не подтверждено провайдером — оценка" : undefined}
                >
                  {ctxEstimated ? "~" : ""}{ctx} ctx
                </Text>
              )}
              {tier === 2 && (
                <Text
                  fontSize="10px"
                  fontWeight="700"
                  fontFamily={typography.fontFamily.mono}
                  color={colors.warning}
                  title="Дорогая модель — быстро расходует кредиты"
                >
                  дорого
                </Text>
              )}
              {tier === 0 && (
                <Text fontSize="10px" fontFamily={typography.fontFamily.mono} color={colors.success} title="Экономная модель">
                  эконом
                </Text>
              )}
              {caps.map((cap) => {
                const CapIcon = CAP_ICON[cap];
                // Без per-item Tooltip — на 300+ моделях это сотни инстансов и лаг;
                // смысл иконки в title (нативная подсказка, нулевая цена).
                return CapIcon ? (
                  <Icon key={cap} as={CapIcon} boxSize="11px" title={CAP_LABEL[cap] || cap} />
                ) : null;
              })}
            </HStack>
          )}
        </VStack>
      </MenuItem>
    );
  };

  return (
    <Menu matchWidth={!isCompact} placement={placement} autoSelect={false} isLazy onClose={() => setQuery("")}>
      <MenuButton
        as={Button}
        variant={isCompact ? "unstyled" : undefined}
        w={isCompact ? "auto" : isMobile ? "100%" : "320px"}
        minW={0}
        maxW={isCompact ? "220px" : undefined}
        h={isCompact ? "28px" : undefined}
        display={isCompact ? "inline-flex" : undefined}
        alignItems={isCompact ? "center" : undefined}
        size={isCompact ? "xs" : "sm"}
        borderRadius={isCompact ? borderRadius.full : borderRadius.md}
        borderWidth="1px"
        borderColor={isAuto ? chat.modelSelector.triggerBorder : chat.modelSelector.triggerBorderActive}
        bg={isAuto ? chat.modelSelector.triggerBg : chat.modelSelector.activeBg}
        color={isAuto ? chat.modelSelector.triggerText : chat.modelSelector.activeText}
        fontFamily={typography.fontFamily.primary}
        fontSize={isCompact ? "12px" : "13px"}
        fontWeight="600"
        px={3}
        overflow="visible"
        _hover={{ bg: isAuto ? chat.modelSelector.triggerBgHover : chat.modelSelector.activeBgHover }}
        _active={{ bg: isAuto ? chat.modelSelector.triggerBgHover : chat.modelSelector.activeBgHover }}
        _focusVisible={isCompact ? { boxShadow: `0 0 0 2px ${colors.border.focus}`, outline: "none" } : undefined}
      >
        <HStack
          align="center"
          spacing={isCompact ? 1.5 : 2}
          minW={0}
          w={isCompact ? undefined : "100%"}
          justify={isCompact ? undefined : "center"}
        >
          {!isAuto && <Icon as={FiCheck} boxSize="12px" color={chat.modelSelector.activeText} flexShrink={0} />}
          <Text noOfLines={1} minW={0} flex="0 1 auto" textAlign={isCompact ? undefined : "center"}>
            {isCompact ? (isAuto ? 'Модель: Auto' : label) : label}
          </Text>
          <Icon as={FiChevronDown} boxSize="12px" color="currentColor" flexShrink={0} />
        </HStack>
      </MenuButton>
      <Portal>
        <MenuList
          bg={chat.modelSelector.menuBg}
          border="1px solid"
          borderColor={chat.modelSelector.menuBorder}
          borderRadius={borderRadius.md}
          py={0}
          maxH="360px"
          minW={isCompact ? "260px" : undefined}
          overflowY="auto"
          zIndex={1600}
          sx={{ backdropFilter: "blur(12px)" }}
        >
          {/* Липкий поиск — навигация по каталогу без бесконечной прокрутки. */}
          <Box position="sticky" top={0} zIndex={1} bg={chat.modelSelector.menuBg} px={2} pt={2} pb={2} borderBottom="1px solid" borderColor={chat.modelSelector.menuBorder}>
            <HStack
              spacing={2}
              px={2.5}
              h="30px"
              borderRadius={borderRadius.sm}
              bg={colors.border.faint}
              border="1px solid"
              borderColor={chat.modelSelector.menuBorder}
            >
              <Icon as={FiSearch} boxSize="13px" color={colors.text.tertiary} flexShrink={0} />
              <Input
                ref={searchRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.stopPropagation()}
                placeholder="Поиск модели…"
                aria-label="Поиск модели"
                variant="unstyled"
                fontSize="13px"
                color={colors.text.primary}
                autoFocus
                _placeholder={{ color: colors.text.tertiary }}
              />
            </HStack>
          </Box>

          <Box py={1}>
            {!query && (
              <MenuItem onClick={() => onChange("")} bg="transparent" _hover={{ bg: chat.modelSelector.itemHover }}>
                <HStack justify="space-between" w="100%">
                  <Text>{AUTO_MODE_LABEL}</Text>
                  {isAuto && <FiCheck />}
                </HStack>
              </MenuItem>
            )}
            {shown.map(renderItem)}
            {hiddenCount > 0 && (
              <Box px={3} py={2} fontSize="11px" color={colors.text.tertiary} fontFamily={typography.fontFamily.mono}>
                …ещё {hiddenCount} — уточните поиск
              </Box>
            )}
            {filtered.length === 0 && (
              <Box px={3} py={3} fontSize="12px" color={colors.text.tertiary}>
                Ничего не найдено
              </Box>
            )}
          </Box>
        </MenuList>
      </Portal>
    </Menu>
  );
}

export default ModelSelector;
