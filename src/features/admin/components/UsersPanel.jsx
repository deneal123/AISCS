import { useCallback, useEffect, useState } from 'react';
import {
  Badge,
  Box,
  Button,
  HStack,
  Input,
  InputGroup,
  InputRightElement,
  Table,
  Tbody,
  Td,
  Th,
  Thead,
  Tr,
  Text,
  VStack,
} from '@chakra-ui/react';
import { CHAT_THEME } from '../../chat/constants/theme';
import { colors, borderRadius } from '@theme/tokens';
import { GLASS_SURFACE, INPUT_BASE } from '@theme/glass';
import { GHOST_BADGE_BLUE_SX, MICRO_LABEL_SX } from '@theme/styles';
import { Skeleton } from '@shared/feedback/Skeleton';
import StateCard from '@shared/feedback/StateCard';
import UserDetailDrawer from './UserDetailDrawer';
import Pager from '@shared/controls/Pager';

const TH_SX = { ...MICRO_LABEL_SX, borderBottom: `1px solid ${colors.border.subtle}`, pb: 2 };
const PAGE_SIZE = 25;

export default function UsersPanel() {
  const [query, setQuery] = useState('');
  const [users, setUsers] = useState(null);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [selectedId, setSelectedId] = useState(null);

  // Серверная пагинация (пользователей могут быть тысячи): limit/offset.
  const load = useCallback(async (q, pageArg) => {
    setLoading(true);
    setError(false);
    const { getAdminUsers } = await import('@api/admin');
    const data = await getAdminUsers(q, {
      limit: PAGE_SIZE,
      offset: pageArg * PAGE_SIZE,
    }).catch(() => null);
    setUsers(data?.users || []);
    setError(!data);
    setLoading(false);
  }, []);

  useEffect(() => {
    load('', 0);
  }, [load]);

  const search = () => {
    setPage(0);
    load(query, 0);
  };
  const goPage = (next) => {
    setPage(next);
    load(query, next);
  };

  const hasMore = (users?.length || 0) === PAGE_SIZE;

  return (
    <VStack align="stretch" spacing={4}>
      <InputGroup maxW="420px">
        <Input
          placeholder="Поиск по email или ID"
          aria-label="Поиск по email или ID"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && search()}
          {...INPUT_BASE}
          pr="4.5rem"
        />
        <InputRightElement w="auto" pr={1}>
          <Button size="sm" onClick={search}>
            Найти
          </Button>
        </InputRightElement>
      </InputGroup>

      {loading ? (
        <VStack align="stretch" spacing={2} aria-busy="true">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} h="52px" radius={borderRadius.sm} />
          ))}
        </VStack>
      ) : error ? (
        <StateCard variant="error" message="Не удалось загрузить пользователей" onRetry={() => load(query, page)} />
      ) : users && users.length === 0 ? (
        <StateCard message={page > 0 ? 'На этой странице пусто' : 'Никого не найдено'} />
      ) : (
        <Box {...GLASS_SURFACE} borderRadius={borderRadius.md} p={4} overflowX="auto" role="region" aria-label="Таблица пользователей" tabIndex={0}>
          <Table size="sm" variant="unstyled" minW="620px">
            <Thead>
              <Tr>
                <Th {...TH_SX}>Пользователь</Th>
                <Th {...TH_SX}>Тариф</Th>
                <Th {...TH_SX} isNumeric>Докуп-баланс</Th>
                <Th {...TH_SX} textAlign="right">Действия</Th>
              </Tr>
            </Thead>
            <Tbody>
              {(users || []).map((u) => (
                <Tr
                  key={u.id}
                  transition="background 140ms ease"
                  opacity={u.is_active ? 1 : 0.6}
                  _hover={{ bg: 'rgba(140,160,255,0.05)' }}
                >
                  <Td color={CHAT_THEME.textPrimary} fontSize="13px">
                    <HStack spacing={2} align="center">
                      <Text noOfLines={1}>{u.email}</Text>
                      {u.is_admin && <Badge fontSize="9px" {...GHOST_BADGE_BLUE_SX}>admin</Badge>}
                      {!u.is_active && (
                        <Badge fontSize="9px" bg={colors.errorSoft} color={colors.error}>заблокирован</Badge>
                      )}
                    </HStack>
                    <Text fontSize="10px" color={CHAT_THEME.textTertiary} fontFamily="mono">{u.id}</Text>
                  </Td>
                  <Td color={CHAT_THEME.textSecondary} fontSize="13px">{u.plan}</Td>
                  <Td color={CHAT_THEME.textSecondary} fontSize="13px" isNumeric>{u.topup_credit_balance}</Td>
                  <Td textAlign="right">
                    <Button size="xs" variant="ghost" color={colors.accent.subtleText} onClick={() => setSelectedId(u.id)}>
                      Управление
                    </Button>
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>

          <Box mt={4}>
            <Pager page={page} hasMore={hasMore} busy={loading} onChange={goPage} />
          </Box>
        </Box>
      )}

      <UserDetailDrawer
        userId={selectedId}
        isOpen={!!selectedId}
        onClose={() => setSelectedId(null)}
        onChanged={() => load(query, page)}
      />
    </VStack>
  );
}
