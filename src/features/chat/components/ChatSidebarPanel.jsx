import React, { useCallback, useMemo, useState } from 'react';
import { Box, Button, HStack, Icon, IconButton, Skeleton, Spinner, Text, VStack } from '@chakra-ui/react';
import { FiCpu, FiEdit2, FiMessageSquare, FiPlus, FiRefreshCw, FiSettings, FiShare2, FiStar, FiX } from '@shared/icons';
import { colors, borderRadius, motion } from '@theme/tokens';
import { CHAT_FONT_FAMILY, CHAT_SCROLLBAR_SX, CHAT_THEME } from '../constants/theme';
import { ChatSidebar } from './index';

const IRIS = colors.iris[300]; // активный акцент-текст (было #9FB0FF литералом)
const EASE = motion.easeOut;
const TRANSITION = `all 160ms ${EASE}`;

function ChatSidebarPanel({
  isSidebarCollapsed,
  filteredRecentThreads,
  isLoadingThreads = false,
  threadsError = false,
  onRetryThreads,
  threadId,
  sidebarSearch,
  setSidebarSearch,
  deletingThreadId,
  handleDeleteThread,
  onNavigateThread,
  onRenameThread,
  pinnedIds,
  onTogglePin,
  onNewChat,
  onOpenMemory,
  onOpenGraph,
  onOpenSettings,
  inDrawer = false,
}) {
  const [editingId, setEditingId] = useState(null);
  const [editValue, setEditValue] = useState('');

  // Закреплённые треды — наверх (stable sort сохраняет исходный порядок внутри групп).
  const sortedThreads = useMemo(() => {
    if (!pinnedIds || pinnedIds.size === 0) return filteredRecentThreads;
    return [...filteredRecentThreads].sort((a, b) => {
      const aPinned = pinnedIds.has(a.thread_id || a.id || a) ? 0 : 1;
      const bPinned = pinnedIds.has(b.thread_id || b.id || b) ? 0 : 1;
      return aPinned - bPinned;
    });
  }, [filteredRecentThreads, pinnedIds]);
  const startEdit = useCallback((tid, current) => { setEditingId(tid); setEditValue(current); }, []);
  const cancelEdit = useCallback(() => { setEditingId(null); setEditValue(''); }, []);
  const commitEdit = useCallback((tid) => {
    const next = editValue.trim();
    setEditingId(null);
    setEditValue('');
    if (next && onRenameThread) onRenameThread(tid, next);
  }, [editValue, onRenameThread]);
  const sidebar = (
    <VStack h="full" align="stretch" spacing={0} p={4}>
      <Box mb={5} px={1}>
        <Text
          fontSize="11px"
          fontWeight="700"
          letterSpacing="0.16em"
          textTransform="uppercase"
          color={colors.blue[300]}
          fontFamily={CHAT_FONT_FAMILY}
        >
          GPTHub
        </Text>
      </Box>

      <Button leftIcon={<FiPlus />} onClick={onNewChat} mb={4} h="40px" borderRadius={borderRadius.sm}
        bg={CHAT_THEME.accentSoft} border={`1px solid ${colors.accent.subtleBorder}`}
        color={colors.blue[300]} fontWeight="600" fontSize="13px" fontFamily={CHAT_FONT_FAMILY}
        _hover={{ bg: colors.accent.hoverSoft, color: 'white', borderColor: colors.accent.base }}
        transition={TRANSITION} justifyContent="flex-start">
        Новый чат
      </Button>

      <Text color={CHAT_THEME.textTertiary} fontSize="11px" fontWeight="600" textTransform="uppercase"
        letterSpacing="0.08em" mb={2} px={1}>
        Последние чаты
      </Text>

      <Box mb={3.5} position="relative">
        <Box as="input" type="text" aria-label="Поиск чатов" placeholder="Поиск чатов..." value={sidebarSearch}
          onChange={(e) => setSidebarSearch(e.target.value)}
          w="100%" h="34px" pl={3} pr={3} borderRadius={borderRadius.sm}
          bg={CHAT_THEME.inputBg} border={`1px solid ${CHAT_THEME.panelBorder}`}
          color={CHAT_THEME.textPrimary} fontSize="13px" fontFamily={CHAT_FONT_FAMILY} outline="none"
          sx={{
            '&::placeholder': { color: CHAT_THEME.textTertiary },
            '&:focus': { borderColor: CHAT_THEME.inputBorderFocus, bg: 'rgba(8,10,20,0.7)' },
            transition: `border-color 160ms ${EASE}, background 160ms ${EASE}`,
          }} />
      </Box>

      <Box flex="1" overflowY="auto" sx={CHAT_SCROLLBAR_SX} mr={-1} pr={1}>
        <VStack spacing={0.5} align="stretch">
          {/* Пусто → отражаем ПРИЧИНУ: загрузка (skeleton) / провал (ошибка+retry) /
              нет данных. Если треды уже есть — показываем их даже при фоновой
              перезагрузке, не мигая скелетоном. */}
          {filteredRecentThreads.length === 0 && isLoadingThreads && (
            <VStack spacing={1} align="stretch" px={0.5} pt={1} aria-busy="true">
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} height="34px" borderRadius={borderRadius.sm}
                  startColor="rgba(140,160,255,0.04)" endColor="rgba(140,160,255,0.12)" speed={0.9} />
              ))}
            </VStack>
          )}
          {filteredRecentThreads.length === 0 && !isLoadingThreads && threadsError && (
            <VStack spacing={2.5} align="stretch" px={2} py={3}>
              <Text color={CHAT_THEME.textTertiary} fontSize="12.5px" lineHeight="1.45">
                Не удалось загрузить чаты
              </Text>
              <Button size="xs" h="30px" leftIcon={<FiRefreshCw />} onClick={onRetryThreads}
                borderRadius={borderRadius.sm} bg={CHAT_THEME.accentSoft}
                border={`1px solid ${colors.accent.subtleBorder}`} color={colors.blue[300]}
                fontWeight="600" fontSize="12px" fontFamily={CHAT_FONT_FAMILY}
                _hover={{ bg: colors.accent.hoverSoft, color: 'white', borderColor: colors.accent.base }}
                transition={TRANSITION} justifyContent="center">
                Повторить
              </Button>
            </VStack>
          )}
          {filteredRecentThreads.length === 0 && !isLoadingThreads && !threadsError && (
            <Text color={CHAT_THEME.textTertiary} fontSize="13px" px={2} py={2}>
              {sidebarSearch ? 'Ничего не найдено' : 'Нет чатов'}
            </Text>
          )}
          {sortedThreads.map((thread) => {
            const tid = thread.thread_id || thread.id || thread;
            const label = thread.title || thread.last_message || `Чат ${String(tid).slice(0, 8)}`;
            const isActive = tid === threadId;
            const isEditing = editingId === tid;
            const isPinned = !!pinnedIds && pinnedIds.has(tid);
            const actionCount = 1 + (onRenameThread ? 1 : 0) + 1; // pin + rename? + delete
            return (
              <Box key={tid} role="group" position="relative">
                {isEditing ? (
                  <Box px={2} py={1}>
                    <Box as="input" type="text" aria-label="Новое название чата" autoFocus value={editValue}
                      onChange={(e) => setEditValue(e.target.value)}
                      onClick={(e) => e.stopPropagation()}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') { e.preventDefault(); commitEdit(tid); }
                        else if (e.key === 'Escape') { e.preventDefault(); cancelEdit(); }
                      }}
                      onBlur={() => commitEdit(tid)}
                      w="100%" h="34px" pl={3} pr={3} borderRadius={borderRadius.sm}
                      bg={CHAT_THEME.inputBg} border={`1px solid ${CHAT_THEME.inputBorderFocus}`}
                      color={CHAT_THEME.textPrimary} fontSize="13.5px" fontFamily={CHAT_FONT_FAMILY} outline="none" />
                  </Box>
                ) : (
                  <>
                    <HStack spacing={2.5} px={3} py={2} pr={`${actionCount * 26 + 4}px`} borderRadius={borderRadius.sm}
                      bg={isActive ? CHAT_THEME.accentSoft : 'transparent'}
                      border={`1px solid ${isActive ? colors.accent.subtleBorder : 'transparent'}`}
                      cursor="pointer"
                      _hover={{ bg: isActive ? CHAT_THEME.accentSoft : CHAT_THEME.panelHover }}
                      onClick={() => onNavigateThread(tid)} transition={TRANSITION} role="button"
                      tabIndex={0}
                      _focusVisible={{ boxShadow: `0 0 0 2px ${colors.border.focus}`, outline: 'none' }}
                      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onNavigateThread(tid); } }}>
                      <Icon as={isPinned ? FiStar : FiMessageSquare}
                        color={isPinned ? IRIS : (isActive ? IRIS : CHAT_THEME.textTertiary)}
                        boxSize="14px" flexShrink={0}
                        sx={isPinned ? { fill: 'currentColor' } : undefined} />
                      <Text color={isActive ? IRIS : CHAT_THEME.textSecondary} fontSize="13.5px"
                        fontWeight={isActive ? '600' : '500'} noOfLines={1} flex="1" letterSpacing="-0.01em">
                        {label}
                      </Text>
                    </HStack>
                    <HStack position="absolute" right="6px" top="50%" transform="translateY(-50%)" spacing={0.5}
                      opacity={inDrawer || isActive || isPinned ? 0.92 : 0} pointerEvents={inDrawer || isActive || isPinned ? 'auto' : 'none'}
                      _groupHover={{ opacity: 1, pointerEvents: 'auto' }} transition={TRANSITION}>
                      {onTogglePin && (
                        <IconButton aria-label={isPinned ? 'Открепить чат' : 'Закрепить чат'} icon={<FiStar />}
                          size="xs" variant="ghost" color={isPinned ? IRIS : CHAT_THEME.textTertiary}
                          borderRadius={borderRadius.sm}
                          sx={isPinned ? { '& svg': { fill: 'currentColor' } } : undefined}
                          _hover={{ bg: colors.accent.hoverSoft, color: IRIS }}
                          onClick={(e) => { e.stopPropagation(); onTogglePin(tid); }} />
                      )}
                      {onRenameThread && (
                        <IconButton aria-label="Переименовать чат" icon={<FiEdit2 />}
                          size="xs" variant="ghost" color={IRIS} borderRadius={borderRadius.sm}
                          _hover={{ bg: colors.accent.hoverSoft, color: IRIS }}
                          onClick={(e) => { e.stopPropagation(); startEdit(tid, label); }} />
                      )}
                      <IconButton aria-label="Удалить чат"
                        icon={deletingThreadId === tid ? <Spinner size="xs" /> : <FiX />}
                        size="xs" variant="ghost" color={IRIS} borderRadius={borderRadius.sm}
                        _hover={{ bg: colors.accent.hoverSoft, color: IRIS }}
                        _active={{ bg: colors.accent.pressSoft }}
                        onClick={(e) => handleDeleteThread(thread, e)}
                        isDisabled={deletingThreadId === tid} />
                    </HStack>
                  </>
                )}
              </Box>
            );
          })}
        </VStack>
      </Box>

      <VStack spacing={1} align="stretch" mt={4} pt={4} borderTop={`1px solid ${CHAT_THEME.panelBorder}`}>
        {[
          { icon: <FiCpu />, label: 'Память и контекст', onClick: onOpenMemory },
          { icon: <FiShare2 />, label: 'Граф знаний', onClick: onOpenGraph },
          { icon: <FiSettings />, label: 'Настройки', onClick: onOpenSettings },
        ].map(({ icon, label, onClick }) => (
          <Button key={label} size="sm" h="34px" justifyContent="flex-start"
            leftIcon={<Box w="16px" h="16px" display="flex" alignItems="center" justifyContent="center" flexShrink={0}>
              {icon}
            </Box>}
            variant="ghost" color={CHAT_THEME.textSecondary} fontSize="13px" fontWeight="500"
            fontFamily={CHAT_FONT_FAMILY} borderRadius={borderRadius.sm}
            _hover={{ bg: CHAT_THEME.panelHover, color: CHAT_THEME.textPrimary }}
            onClick={onClick} transition={TRANSITION}>
            {label}
          </Button>
        ))}
      </VStack>
    </VStack>
  );

  return (
    <ChatSidebar isCollapsed={inDrawer ? false : isSidebarCollapsed} inDrawer={inDrawer}>
      <Box
        bg={CHAT_THEME.sidebarBg}
        h="full"
        borderRight={inDrawer ? 'none' : `1px solid ${CHAT_THEME.panelBorder}`}
        // Внутри мобильного Drawer'а backdrop-blur НЕ вешаем: блюр во всю высоту
        // пере-растеризуется на КАЖДОМ кадре слайд-анимации и заметно её тормозит
        // (ровно то, от чего предостерегает @theme/drawer). Панель дровера и так
        // почти непрозрачная — блюр там визуально ничего не добавляет.
        backdropFilter={inDrawer ? undefined : 'blur(14px)'}
      >
        {sidebar}
      </Box>
    </ChatSidebar>
  );
}

export default React.memo(ChatSidebarPanel);
