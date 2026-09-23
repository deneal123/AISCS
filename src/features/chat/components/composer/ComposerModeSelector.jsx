import React from 'react';
import { Button, HStack, Icon, Menu, MenuButton, MenuDivider, MenuItem, MenuList, Text, Tooltip } from '@chakra-ui/react';
import { FiChevronDown, FiCheck, FiZap, FiGlobe, FiSearch, FiImage, FiFileText, FiMessageCircle, FiGitBranch, FiLayers } from '@shared/icons';
import { colors, borderRadius } from '@theme/tokens';
import { CHAT_FONT_FAMILY, CHAT_THEME } from '../../constants/theme';
import BetaTag from '../BetaTag';

const IRIS = colors.iris[300];

// Принудительный выбор режима/агента. value === null -> Авто (LLM-роутер + тогглы).
// Прочие значения уходят как route_override и форсируют конкретного агента.
// Иконки react-icons вместо эмодзи (единый визуальный язык, не off-brand).
// beta: помечаем <BetaTag/> только презентации (остальные — стабильны).
// ⚠️ Подсказки переехали сюда с отдельных кнопок-тумблеров, которые дублировали это
// меню (и тоггл, и режим резолвились в одну категорию). Терять их было нельзя: про
// «дольше и дороже» человеку важно знать ДО отправки, а не по счёту после.
export const CHAT_MODES = [
  {
    value: null,
    label: 'Авто',
    icon: FiZap,
    hint: 'Роутер сам выбирает подходящий режим под каждое сообщение — один на запрос. '
      + 'Здесь же работают планирование сложных задач и мульти-интент.',
  },
  {
    value: 'web_search',
    label: 'Веб-поиск',
    icon: FiGlobe,
    hint: 'Ищет актуальные данные в интернете и цитирует источники — для свежих фактов, '
      + 'цен, новостей. Берётся надбавка за поиск.',
  },
  {
    value: 'deep_research',
    label: 'Deep Research',
    icon: FiSearch,
    hint: 'Многошаговое исследование: собирает и сопоставляет источники, готовит '
      + 'развёрнутый отчёт. Дольше и заметно дороже обычного ответа.',
  },
  { value: 'image_gen', label: 'Изображение', icon: FiImage, hint: 'Генерирует картинку по описанию. Надбавка берётся за созданный файл.' },
  { value: 'pptx_gen', label: 'Презентация', icon: FiFileText, beta: true, hint: 'Собирает .pptx со структурой и иллюстрациями. Надбавка — за файл.' },
  { value: 'general', label: 'Обычный', icon: FiMessageCircle, hint: 'Без инструментов и без планирования: прямой ответ модели.' },
];

const PLANNING_HINT = 'Агент строит короткий план решения и отвечает по нему. Выключено — '
  + 'НЕ «никогда»: план и так строится сам на задачах, признанных сложными. Включено — '
  + 'строить всегда (и без отдельного вызова-оценки).';

const MULTI_INTENT_HINT = 'Разбивает запрос с несколькими задачами на под-шаги и выполняет '
  + 'их по очереди, каждый своим режимом. Полезно для составных просьб «сделай A, затем B».';

/** Пункт меню с подсказкой справа: режим меняет и цену, и длительность ответа. */
function HintedItem({ hint, children }) {
  if (!hint) return children;
  return (
    <Tooltip
      label={hint}
      placement="right"
      hasArrow
      openDelay={300}
      bg={CHAT_THEME.sidebarBg}
      color={CHAT_THEME.textPrimary}
      border={`1px solid ${CHAT_THEME.panelBorder}`}
      borderRadius={borderRadius.sm}
      fontSize="12px"
      fontWeight="500"
      px={3}
      py={2}
      maxW="260px"
    >
      {children}
    </Tooltip>
  );
}

function ComposerModeSelector({
  value = null, onChange,
  multiIntentEnabled = false, onToggleMultiIntent,
  planningEnabled = false, onTogglePlanning,
}) {
  const current = CHAT_MODES.find((m) => m.value === value) || CHAT_MODES[0];
  const isForced = value != null;

  return (
    <Menu placement="top-start" autoSelect={false} isLazy>
      <MenuButton
        as={Button}
        size="xs"
        h="28px"
        px={3}
        borderRadius={borderRadius.full}
        variant="unstyled"
        fontSize="12px"
        fontWeight="600"
        fontFamily={CHAT_FONT_FAMILY}
        bg={isForced ? CHAT_THEME.accentSoft : CHAT_THEME.panelHover}
        color={isForced ? IRIS : CHAT_THEME.textSecondary}
        border={`1px solid ${isForced ? colors.accent.subtleBorder : CHAT_THEME.panelBorder}`}
        _hover={{ color: CHAT_THEME.textPrimary }}
      >
        <HStack as="span" spacing={1.5} justify="center">
          <Icon as={current.icon} boxSize="13px" />
          <Text as="span">Режим: {current.label}</Text>
          {current.beta && <BetaTag />}
          <Icon as={FiChevronDown} boxSize={3} />
        </HStack>
      </MenuButton>
      <MenuList
        bg={CHAT_THEME.sidebarBg}
        borderColor={CHAT_THEME.panelBorder}
        borderRadius={borderRadius.md}
        minW="210px"
        py={1}
        zIndex={30}
        sx={{ backdropFilter: 'blur(22px)' }}
      >
        {CHAT_MODES.map((mode) => {
          const selected = mode.value === value;
          return (
            <HintedItem key={mode.value ?? 'auto'} hint={mode.hint}>
              <MenuItem
                onClick={() => onChange?.(mode.value)}
                bg="transparent"
                _hover={{ bg: CHAT_THEME.panelHover }}
                _focus={{ bg: CHAT_THEME.panelHover }}
                color={selected ? IRIS : CHAT_THEME.textPrimary}
                fontSize="13px"
                fontFamily={CHAT_FONT_FAMILY}
              >
                <Icon as={mode.icon} boxSize="14px" mr={2} />
                <Text as="span">{mode.label}</Text>
                {mode.beta && <BetaTag ml={1.5} />}
                {selected && <Icon as={FiCheck} boxSize="14px" ml="auto" color={IRIS} />}
              </MenuItem>
            </HintedItem>
          );
        })}
        {/* Мульти-интент — стратегия (не форс-маршрут): тоггл поверх «Авто».
            Показываем только в Авто-режиме, где декомпозиция и работает. */}
        {value == null && onToggleMultiIntent && (
          <>
            <MenuDivider borderColor={CHAT_THEME.panelBorder} my={1} />
            <HintedItem hint={MULTI_INTENT_HINT}>
              <MenuItem
                onClick={onToggleMultiIntent}
                closeOnSelect={false}
                bg="transparent"
                _hover={{ bg: CHAT_THEME.panelHover }}
                _focus={{ bg: CHAT_THEME.panelHover }}
                color={multiIntentEnabled ? IRIS : CHAT_THEME.textPrimary}
                fontSize="13px"
                fontFamily={CHAT_FONT_FAMILY}
              >
                <Icon as={FiGitBranch} boxSize="14px" mr={2} />
                <Text as="span">Мульти-интент</Text>
                {multiIntentEnabled && <Icon as={FiCheck} boxSize="14px" ml="auto" color={IRIS} />}
              </MenuItem>
            </HintedItem>
            {onTogglePlanning && (
              <HintedItem hint={PLANNING_HINT}>
                <MenuItem
                  onClick={onTogglePlanning}
                  closeOnSelect={false}
                  bg="transparent"
                  _hover={{ bg: CHAT_THEME.panelHover }}
                  _focus={{ bg: CHAT_THEME.panelHover }}
                  color={planningEnabled ? IRIS : CHAT_THEME.textPrimary}
                  fontSize="13px"
                  fontFamily={CHAT_FONT_FAMILY}
                >
                  <Icon as={FiLayers} boxSize="14px" mr={2} />
                  <Text as="span">Планирование</Text>
                  {planningEnabled && <Icon as={FiCheck} boxSize="14px" ml="auto" color={IRIS} />}
                </MenuItem>
              </HintedItem>
            )}
          </>
        )}
      </MenuList>
    </Menu>
  );
}

export default ComposerModeSelector;
