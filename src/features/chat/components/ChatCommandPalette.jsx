import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Box, HStack, Icon, Input, Kbd, Modal, ModalContent, ModalOverlay, Text, VStack,
} from '@chakra-ui/react';
import { FiCornerDownLeft, FiCpu, FiDatabase, FiDownload, FiMessageSquare, FiPlus, FiSearch, FiSettings } from '@shared/icons';
import { colors, borderRadius, motion } from '@theme/tokens';
import { GLASS_SURFACE_STRONG } from '@theme/glass';
import { CHAT_FONT_FAMILY, CHAT_THEME } from '../constants/theme';

/**
 * Командная палитра чата (Cmd/Ctrl+K): новый чат, переход к недавним тредам,
 * смена модели, настройки, память. Клавиатура: ↑/↓ выбор, Enter запуск, Esc закрыть.
 * Стекло из @theme/glass, единый blue-акцент.
 */
export default function ChatCommandPalette({ isOpen, onClose, actions = {}, recentThreads = [], models = [] }) {
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const listRef = useRef(null);

  const items = useMemo(() => {
    const base = [
      { id: 'new', label: 'Новый чат', sub: 'Начать с чистого листа', icon: FiPlus, run: actions.newChat },
      { id: 'export', label: 'Экспорт в Markdown', sub: 'Скачать этот чат файлом .md', icon: FiDownload, run: actions.exportChat },
      { id: 'settings', label: 'Настройки чата', sub: 'Трейс, инструменты', icon: FiSettings, run: actions.openSettings },
      { id: 'memory', label: 'Память', sub: 'Факты об этом пользователе', icon: FiDatabase, run: actions.openMemory },
      { id: 'model_auto', label: 'Модель: Auto', sub: 'Автовыбор роутером', icon: FiCpu, run: () => actions.selectModel?.('') },
    ];
    const modelItems = (models || []).map((m) => ({
      id: `model_${m}`, label: `Модель: ${m}`, sub: 'Зафиксировать модель', icon: FiCpu, run: () => actions.selectModel?.(m),
    }));
    const threadItems = (recentThreads || []).map((t) => {
      const tid = t?.thread_id || t?.id || t;
      const title = t?.title || t?.name || String(tid);
      return { id: `thread_${tid}`, label: title, sub: 'Перейти к чату', icon: FiMessageSquare, run: () => actions.goToThread?.(tid) };
    });
    return [...base, ...modelItems, ...threadItems];
  }, [actions, models, recentThreads]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter((it) => it.label.toLowerCase().includes(q) || (it.sub || '').toLowerCase().includes(q));
  }, [items, query]);

  useEffect(() => {
    if (isOpen) { setQuery(''); setActive(0); }
  }, [isOpen]);
  useEffect(() => { setActive(0); }, [query]);

  const run = (item) => {
    if (!item) return;
    onClose();
    // Отложить действие на тик — сначала даём палитре закрыться (иначе фокус/дровер конфликтуют).
    setTimeout(() => item.run?.(), 0);
  };

  const onInputKeyDown = (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, filtered.length - 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === 'Enter') { e.preventDefault(); run(filtered[active]); }
  };

  useEffect(() => {
    const el = listRef.current?.querySelector(`[data-idx="${active}"]`);
    el?.scrollIntoView({ block: 'nearest' });
  }, [active]);

  return (
    <Modal isOpen={isOpen} onClose={onClose} isCentered motionPreset="none" size="lg">
      <ModalOverlay bg="rgba(3,5,12,0.6)" backdropFilter="blur(4px)" />
      <ModalContent {...GLASS_SURFACE_STRONG} borderRadius={borderRadius.lg} overflow="hidden" mt="12vh" bg={CHAT_THEME.sidebarBg}>
        <HStack px={4} py={3} spacing={3} borderBottom={`1px solid ${CHAT_THEME.panelBorder}`}>
          <Icon as={FiSearch} boxSize="16px" color={CHAT_THEME.textTertiary} />
          <Input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onInputKeyDown}
            placeholder="Команда, модель или чат…"
            aria-label="Поиск команды, модели или чата"
            variant="unstyled"
            fontSize="15px"
            fontFamily={CHAT_FONT_FAMILY}
            color={CHAT_THEME.textPrimary}
            _placeholder={{ color: CHAT_THEME.textTertiary }}
          />
          <Kbd fontSize="10px" bg={CHAT_THEME.panelHover} color={CHAT_THEME.textTertiary} borderColor={CHAT_THEME.panelBorder}>esc</Kbd>
        </HStack>

        <VStack ref={listRef} align="stretch" spacing={0} maxH="46vh" overflowY="auto" py={2} px={2}
          sx={{ scrollbarWidth: 'thin' }}>
          {filtered.length === 0 ? (
            <Text px={3} py={6} textAlign="center" fontSize="13px" color={CHAT_THEME.textTertiary}>
              Ничего не найдено
            </Text>
          ) : filtered.map((item, idx) => {
            const isActive = idx === active;
            return (
              <HStack
                key={item.id}
                data-idx={idx}
                as="button"
                type="button"
                onMouseEnter={() => setActive(idx)}
                onClick={() => run(item)}
                spacing={3}
                px={3}
                py={2.5}
                borderRadius={borderRadius.sm}
                textAlign="left"
                bg={isActive ? CHAT_THEME.panelActive : 'transparent'}
                transition={`background 120ms ${motion.easeOut}`}
              >
                <Icon as={item.icon} boxSize="15px" color={isActive ? colors.blue[300] : CHAT_THEME.textSecondary} flexShrink={0} />
                <Box minW={0} flex="1">
                  <Text fontSize="13.5px" fontWeight="600" color={CHAT_THEME.textPrimary} noOfLines={1}>{item.label}</Text>
                  {item.sub && <Text fontSize="11px" color={CHAT_THEME.textTertiary} noOfLines={1}>{item.sub}</Text>}
                </Box>
                {isActive && <Icon as={FiCornerDownLeft} boxSize="13px" color={CHAT_THEME.textTertiary} flexShrink={0} />}
              </HStack>
            );
          })}
        </VStack>
      </ModalContent>
    </Modal>
  );
}
