import React from 'react';
import { Button, HStack, Icon, Menu, MenuButton, MenuDivider, MenuItem, MenuList, Text, Tooltip } from '@chakra-ui/react';
import { FiChevronDown, FiCheck, FiUser } from '@shared/icons';
import { colors, borderRadius } from '@theme/tokens';
import { CHAT_FONT_FAMILY, CHAT_THEME } from '../../constants/theme';

const IRIS = colors.iris[300];

// Потолок должен совпадать с MAX_ACTIVE сайдкара: там лишние молча отбрасываются, и без
// зеркального ограничения пользователь выбрал бы третью личность, не поняв, почему она не
// действует. ДВЕ — это и есть «связка»: пара даёт новый угол, тройка размывает каждую.
export const MAX_PERSONAS = 2;

// Подсказка приходит ИЗ РЕЕСТРА (каталог сайдкара), а не зашита здесь: личности правятся
// JSON-ом в админке, и новая обязана объясняться сама, без выката фронта. Ровно поэтому
// рядом лежит карта иконок — визуальный слой реестр знать не должен, а текст должен.
function PersonaHint({ hint, children }) {
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
      maxW="280px"
    >
      {children}
    </Tooltip>
  );
}

// Третья ось выбора рядом с режимом и моделью. Режим — ЧТО делать, модель — ЧЕМ думать,
// личность — КАК думать. Оси ортогональны, поэтому селектор отдельный, а не пункт в режиме.
function ComposerPersonaSelector({ personas = [], value = [], onChange }) {
  // Личностей не объявлено (или сайдкар недоступен) — селектор просто не показываем:
  // пустое меню выглядит как поломка.
  if (!personas.length) return null;

  const selected = Array.isArray(value) ? value : [];
  // ⚠️ Порядок берём из ВЫБОРА, а не из каталога. Первая выбранная — ведущая: её тон и
  // формат ответа получает связка. Фильтр по каталогу показывал бы пару в чужом порядке,
  // и подпись «Психолог + Таролог» противоречила бы тому, чей голос звучит.
  const active = selected.map((id) => personas.find((p) => p.id === id)).filter(Boolean);
  const atCap = selected.length >= MAX_PERSONAS;

  const toggle = (id) => {
    if (selected.includes(id)) {
      onChange?.(selected.filter((x) => x !== id));
      return;
    }
    if (atCap) return;
    onChange?.([...selected, id]);
  };

  const label = active.length
    ? active.map((p) => p.label).join(' + ')
    : 'Обычная';

  return (
    <Menu placement="top-start" autoSelect={false} isLazy closeOnSelect={false}>
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
        bg={active.length ? CHAT_THEME.accentSoft : CHAT_THEME.panelHover}
        color={active.length ? IRIS : CHAT_THEME.textSecondary}
        border={`1px solid ${active.length ? colors.accent.subtleBorder : CHAT_THEME.panelBorder}`}
        _hover={{ color: CHAT_THEME.textPrimary }}
      >
        <HStack as="span" spacing={1.5} justify="center">
          <Icon as={FiUser} boxSize="13px" />
          <Text as="span" noOfLines={1} maxW="180px">Личность: {label}</Text>
          <Icon as={FiChevronDown} boxSize={3} />
        </HStack>
      </MenuButton>
      <MenuList
        bg={CHAT_THEME.sidebarBg}
        borderColor={CHAT_THEME.panelBorder}
        borderRadius={borderRadius.md}
        minW="230px"
        py={1}
        zIndex={30}
        sx={{ backdropFilter: 'blur(22px)' }}
      >
        {personas.map((p) => {
          const isOn = selected.includes(p.id);
          // Недоступные при достигнутом потолке гасим, но НЕ прячем: исчезающий пункт
          // читается как «личность пропала», а не «сначала сними другую».
          const muted = !isOn && atCap;
          return (
            <PersonaHint key={p.id} hint={p.hint}>
            <MenuItem
              onClick={() => toggle(p.id)}
              bg="transparent"
              _hover={{ bg: muted ? 'transparent' : CHAT_THEME.panelHover }}
              _focus={{ bg: muted ? 'transparent' : CHAT_THEME.panelHover }}
              color={isOn ? IRIS : CHAT_THEME.textPrimary}
              opacity={muted ? 0.45 : 1}
              cursor={muted ? 'not-allowed' : 'pointer'}
              fontSize="13px"
              fontFamily={CHAT_FONT_FAMILY}
            >
              <Text as="span">{p.label}</Text>
              {/* Ведущую называем только в связке: у одиночной личности выбора нет и
                  подпись была бы шумом. */}
              {isOn && selected.length > 1 && selected[0] === p.id && (
                <Text as="span" ml={2} fontSize="11px" color={CHAT_THEME.textTertiary}>
                  ведущая
                </Text>
              )}
              {isOn && <Icon as={FiCheck} boxSize="14px" ml="auto" color={IRIS} />}
            </MenuItem>
            </PersonaHint>
          );
        })}
        {selected.length > 0 && (
          <>
            <MenuDivider borderColor={CHAT_THEME.panelBorder} my={1} />
            <MenuItem
              onClick={() => onChange?.([])}
              bg="transparent"
              _hover={{ bg: CHAT_THEME.panelHover }}
              _focus={{ bg: CHAT_THEME.panelHover }}
              color={CHAT_THEME.textSecondary}
              fontSize="13px"
              fontFamily={CHAT_FONT_FAMILY}
            >
              <Text as="span">Без личности</Text>
            </MenuItem>
          </>
        )}
      </MenuList>
    </Menu>
  );
}

export default React.memo(ComposerPersonaSelector);
