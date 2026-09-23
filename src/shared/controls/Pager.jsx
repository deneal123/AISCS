import { HStack, Icon, IconButton, Text } from '@chakra-ui/react';
import { FiChevronLeft, FiChevronRight } from '@shared/icons';
import { colors } from '@theme/tokens';

/**
 * Постраничная навигация «‹ Стр. N из M ›» — единый пейджер приложения
 * (админ-таблицы, история операций, история пользователя). Раньше эти четыре
 * места несли четыре копии одной разметки, и они уже разъезжались: где-то был
 * счётчик страниц, где-то нет; где-то блокировка на время загрузки, где-то нет.
 *
 * Два режима:
 *   - известно общее число страниц → `pageCount` («Стр. 2 из 3»);
 *   - известно только «есть ли ещё» → `hasMore` («Стр. 2»).
 *
 * @param {number} page       текущая страница, с нуля
 * @param {number} [pageCount] всего страниц (если известно)
 * @param {boolean} [hasMore]  есть ли следующая (когда pageCount неизвестен)
 * @param {(page: number) => void} onChange
 * @param {boolean} [busy]     блокирует кнопки на время запроса
 * @param {'xs'|'sm'} [size]
 */
export default function Pager({ page, pageCount, hasMore = false, onChange, busy = false, size = 'sm' }) {
  const known = Number.isFinite(pageCount);
  const canPrev = page > 0;
  const canNext = known ? page < pageCount - 1 : hasMore;

  // Нечего листать — не показываем пейджер вовсе.
  if (!canPrev && !canNext) return null;

  const labelSize = size === 'xs' ? '11px' : '12px';
  return (
    <HStack justify="center" spacing={size === 'xs' ? 1 : 3}>
      <IconButton
        aria-label="Предыдущая страница"
        size={size}
        variant="ghost"
        icon={<Icon as={FiChevronLeft} />}
        isDisabled={!canPrev || busy}
        onClick={() => onChange(page - 1)}
      />
      <Text fontSize={labelSize} color={colors.fg[3]} whiteSpace="nowrap">
        Стр. {page + 1}
        {known ? ` из ${pageCount}` : ''}
      </Text>
      <IconButton
        aria-label="Следующая страница"
        size={size}
        variant="ghost"
        icon={<Icon as={FiChevronRight} />}
        isDisabled={!canNext || busy}
        onClick={() => onChange(page + 1)}
      />
    </HStack>
  );
}
