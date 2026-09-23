import { useCallback, useEffect, useRef, useState } from 'react';
import {
  AlertDialog,
  AlertDialogBody,
  AlertDialogContent,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogOverlay,
  Badge,
  Box,
  Button,
  Drawer,
  DrawerBody,
  DrawerCloseButton,
  DrawerContent,
  DrawerHeader,
  DrawerOverlay,
  HStack,
  Icon,
  NumberInput,
  NumberInputField,
  Text,
  VStack,
  useDisclosure,
} from '@chakra-ui/react';
import { FiClock } from '@shared/icons';
import { CHAT_THEME } from '../../chat/constants/theme';
import { colors, borderRadius } from '@theme/tokens';
import { DRAWER_CLOSE_BUTTON_PROPS, DRAWER_CONTENT_BG } from '@theme/drawer';
import { GLASS_SURFACE, GLASS_SURFACE_STRONG, INPUT_BASE } from '@theme/glass';
import { GHOST_BADGE_BLUE_SX, GHOST_BUTTON_BLUE_SX, MICRO_LABEL_SX } from '@theme/styles';
import { Skeleton } from '@shared/feedback/Skeleton';
import Pager from '@shared/controls/Pager';
import AppSelect from '@shared/controls/AppSelect';
import { useAppToast } from '@shared/hooks/useAppToast';

const PLAN_OPTIONS = ['free', 'pro', 'enterprise'];
const EV_PAGE_SIZE = 8;

/** Дровер управления пользователем: тариф, баланс, роль, блокировка, история. */
export default function UserDetailDrawer({ userId, isOpen, onClose, onChanged }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(false);
  const [plan, setPlan] = useState('free');
  const [balance, setBalance] = useState(0);
  const [busy, setBusy] = useState('');
  const [events, setEvents] = useState(null);
  const [evPage, setEvPage] = useState(0);
  const [evLoading, setEvLoading] = useState(false);
  const [evHasMore, setEvHasMore] = useState(false);
  const toast = useAppToast();
  const blockDlg = useDisclosure();
  const cancelRef = useRef(null);

  const load = useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    const { getAdminUser } = await import('@api/admin');
    const u = await getAdminUser(userId).catch(() => null);
    setUser(u);
    setPlan(u?.plan || 'free');
    setBalance(u?.topup_credit_balance ?? 0);
    setLoading(false);
  }, [userId]);

  // Пагинация истории операций (тысячи событий → нет смысла грузить все).
  const loadEvents = useCallback(
    async (page) => {
      if (!userId) return;
      setEvLoading(true);
      const { getUserEvents } = await import('@api/admin');
      const data = await getUserEvents(userId, {
        limit: EV_PAGE_SIZE,
        offset: page * EV_PAGE_SIZE,
      }).catch(() => null);
      const list = data?.events || [];
      setEvents(list);
      setEvHasMore(list.length === EV_PAGE_SIZE);
      setEvPage(page);
      setEvLoading(false);
    },
    [userId],
  );

  useEffect(() => {
    if (isOpen) {
      load();
      loadEvents(0);
    }
  }, [isOpen, load, loadEvents]);

  const afterChange = async () => {
    await load();
    await loadEvents(0); // новое событие появляется вверху первой страницы
    onChanged?.();
  };

  const run = async (tag, fn, okTitle) => {
    setBusy(tag);
    try {
      await fn();
      toast({ title: okTitle, status: 'success', duration: 1500 });
      await afterChange();
    } catch (e) {
      toast({ title: e?.response?.data?.detail || 'Ошибка', status: 'error', duration: 2500 });
    } finally {
      setBusy('');
    }
  };

  const applyPlan = () =>
    run('plan', async () => (await import('@api/admin')).setUserPlan(userId, plan), 'Тариф обновлён');
  const applyBalance = () =>
    run('balance', async () =>
      (await import('@api/admin')).setUserBalance(userId, Number(balance) || 0, 'admin panel'),
    'Баланс задан');
  const toggleAdmin = () =>
    run('admin', async () => (await import('@api/admin')).setUserRole(userId, !user.is_admin), 'Роль обновлена');
  const toggleBlock = () => {
    blockDlg.onClose();
    run('block', async () => (await import('@api/admin')).setUserActive(userId, !user.is_active),
      user.is_active ? 'Пользователь заблокирован' : 'Пользователь разблокирован');
  };

  return (
    <Drawer isOpen={isOpen} placement="right" onClose={onClose} size="md">
      <DrawerOverlay bg={colors.bg.overlay} />
      <DrawerContent {...GLASS_SURFACE_STRONG} bg={DRAWER_CONTENT_BG}>
        <DrawerCloseButton aria-label="Закрыть карточку пользователя" color={CHAT_THEME.textSecondary} {...DRAWER_CLOSE_BUTTON_PROPS} />
        <DrawerHeader color={CHAT_THEME.textPrimary} fontSize="16px">
          Управление пользователем
        </DrawerHeader>
        <DrawerBody pb={6}>
          {loading || !user ? (
            <VStack align="stretch" spacing={3}>
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} h="64px" radius={borderRadius.md} />
              ))}
            </VStack>
          ) : (
            <VStack align="stretch" spacing={5}>
              <Box p={4} {...GLASS_SURFACE} borderRadius={borderRadius.md}>
                <HStack justify="space-between" mb={1} align="start">
                  <Text fontSize="15px" fontWeight="700" color={CHAT_THEME.textPrimary} noOfLines={1}>
                    {user.email}
                  </Text>
                  <HStack spacing={1} flexShrink={0}>
                    {user.is_admin && <Badge {...GHOST_BADGE_BLUE_SX} fontSize="9px">admin</Badge>}
                    <Badge
                      fontSize="9px"
                      bg={user.is_active ? colors.successSoft : colors.errorSoft}
                      color={user.is_active ? colors.success : colors.error}
                    >
                      {user.is_active ? 'активен' : 'заблокирован'}
                    </Badge>
                  </HStack>
                </HStack>
                <Text fontSize="10px" fontFamily="mono" color={CHAT_THEME.textTertiary}>{user.id}</Text>
                <HStack mt={2} spacing={5}>
                  <Text fontSize="12px" color={CHAT_THEME.textSecondary}>Тариф: {user.plan}</Text>
                  <Text fontSize="12px" color={CHAT_THEME.textSecondary}>Баланс: {user.topup_credit_balance}</Text>
                </HStack>
              </Box>

              <Box>
                <Text {...MICRO_LABEL_SX} mb={2}>Тариф</Text>
                <HStack>
                  <AppSelect
                    value={plan}
                    onChange={setPlan}
                    ariaLabel="Тариф"
                    maxW="200px"
                    options={PLAN_OPTIONS.map((item) => ({ value: item, label: item }))}
                  />
                  <Button size="sm" onClick={applyPlan} isLoading={busy === 'plan'} {...GHOST_BUTTON_BLUE_SX}>
                    Применить
                  </Button>
                </HStack>
              </Box>

              <Box>
                <Text {...MICRO_LABEL_SX} mb={2}>Докуп-баланс (задать абсолютно)</Text>
                <HStack>
                  <NumberInput value={balance} min={0} onChange={(_, n) => setBalance(Number.isNaN(n) ? 0 : n)} maxW="200px">
                    <NumberInputField {...INPUT_BASE} />
                  </NumberInput>
                  <Button size="sm" onClick={applyBalance} isLoading={busy === 'balance'} {...GHOST_BUTTON_BLUE_SX}>
                    Задать
                  </Button>
                </HStack>
              </Box>

              <Box>
                <Text {...MICRO_LABEL_SX} mb={2}>Доступ</Text>
                <HStack spacing={2}>
                  <Button size="sm" variant="outline" onClick={toggleAdmin} isLoading={busy === 'admin'}>
                    {user.is_admin ? 'Снять admin' : 'Сделать admin'}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={blockDlg.onOpen}
                    isLoading={busy === 'block'}
                    colorScheme={user.is_active ? 'red' : 'green'}
                  >
                    {user.is_active ? 'Заблокировать' : 'Разблокировать'}
                  </Button>
                </HStack>
              </Box>

              <Box>
                <HStack justify="space-between" mb={2}>
                  <Text {...MICRO_LABEL_SX}>История операций</Text>
                  <Pager
                    page={evPage}
                    hasMore={evHasMore}
                    busy={evLoading}
                    size="xs"
                    onChange={loadEvents}
                  />
                </HStack>
                <VStack align="stretch" spacing={1.5} opacity={evLoading ? 0.5 : 1} transition="opacity 120ms">
                  {events && events.length === 0 && (
                    <Text fontSize="12px" color={CHAT_THEME.textTertiary}>
                      {evPage > 0 ? 'На этой странице пусто' : 'Нет операций'}
                    </Text>
                  )}
                  {(events || []).map((e, i) => (
                    <HStack key={i} justify="space-between" p={2.5} {...GLASS_SURFACE} borderRadius={borderRadius.sm}>
                      <HStack spacing={2} minW={0}>
                        <Icon as={FiClock} boxSize={3} color={CHAT_THEME.textTertiary} />
                        <Text fontSize="12px" color={CHAT_THEME.textSecondary} noOfLines={1}>{e.event_type}</Text>
                      </HStack>
                      <Text fontSize="11px" color={CHAT_THEME.textTertiary} flexShrink={0}>
                        {(e.created_at || '').slice(0, 16).replace('T', ' ')}
                      </Text>
                    </HStack>
                  ))}
                </VStack>
              </Box>
            </VStack>
          )}
        </DrawerBody>
      </DrawerContent>

      <AlertDialog isOpen={blockDlg.isOpen} leastDestructiveRef={cancelRef} onClose={blockDlg.onClose} isCentered>
        <AlertDialogOverlay>
          <AlertDialogContent {...GLASS_SURFACE_STRONG} color={CHAT_THEME.textPrimary}>
            <AlertDialogHeader fontSize="md">
              {user?.is_active ? 'Заблокировать пользователя?' : 'Разблокировать пользователя?'}
            </AlertDialogHeader>
            <AlertDialogBody fontSize="sm" color={CHAT_THEME.textSecondary}>
              {user?.is_active
                ? 'Пользователь не сможет войти, а его активные сессии будут сброшены.'
                : 'Пользователь снова сможет входить в аккаунт.'}
            </AlertDialogBody>
            <AlertDialogFooter>
              <Button ref={cancelRef} onClick={blockDlg.onClose} size="sm" variant="ghost">Отмена</Button>
              <Button onClick={toggleBlock} size="sm" ml={3} colorScheme={user?.is_active ? 'red' : 'green'}>
                {user?.is_active ? 'Заблокировать' : 'Разблокировать'}
              </Button>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialogOverlay>
      </AlertDialog>
    </Drawer>
  );
}
