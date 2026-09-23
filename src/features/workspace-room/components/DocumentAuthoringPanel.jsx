import {
  Badge,
  Box,
  Button,
  HStack,
  Spinner,
  Text,
  VStack,
} from '@chakra-ui/react';
import { colors, borderRadius } from '@theme/tokens';

const KIND_LABELS = {
  generic: 'Документ',
  article: 'Статья',
  presentation: 'Презентация',
  legal: 'Юридический документ',
  report: 'Отчёт',
};

const BLOCK_LABELS = {
  section: 'Раздел',
  paragraph: 'Абзац',
  list: 'Список',
  table: 'Таблица',
  figure: 'Иллюстрация',
  equation: 'Формула',
  callout: 'Выноска',
  slide: 'Слайд',
  signature: 'Подписи',
  citation: 'Цитирование',
};

const safeKind = (value) => KIND_LABELS[value] || 'Документ';
const safeBlock = (value) => BLOCK_LABELS[value] || 'Блок документа';

function BriefFacts({ intent, draft }) {
  const citationCount = (draft?.blocks || []).filter(
    (item) => Number(item?.source_id || 0) > 0,
  ).length;
  const unresolved = (intent?.legal_fields || []).filter((item) => item?.required && !item?.value);
  return (
    <VStack align="stretch" spacing={1.5}>
      <HStack justify="space-between" align="start">
        <Box minW={0}>
          <Text fontSize="10.5px" color={colors.fg[4]}>Замысел</Text>
          <Text fontSize="12px" color={colors.fg[2]} noOfLines={2}>
            {intent?.title || draft?.title || 'Без названия'}
          </Text>
        </Box>
        <Badge colorScheme="gray" flexShrink={0}>{safeKind(intent?.kind)}</Badge>
      </HStack>
      <Text fontSize="10.5px" color={colors.fg[4]}>
        Аудитория: {intent?.audience || 'не указана'}
      </Text>
      <Text fontSize="10.5px" color={colors.fg[4]}>
        Источники: {intent?.citation_policy === 'required' ? 'обязательны' : 'по необходимости'}
        {' · '}ссылок в структуре: {citationCount}
      </Text>
      {unresolved.length > 0 && (
        <Text role="status" fontSize="10.5px" color={colors.warning}>
          Не заполнено обязательных реквизитов: {unresolved.length}. Финал будет заблокирован.
        </Text>
      )}
    </VStack>
  );
}

export function DocumentAuthoringPanel({ authoring, onOpenSource }) {
  const state = authoring?.state || 'idle';
  const value = authoring?.value;
  const draft = value?.draft;
  const intent = value?.intent;
  const blocks = Array.isArray(draft?.blocks) ? draft.blocks : [];
  const blockFiles = value?.block_files && typeof value.block_files === 'object'
    ? value.block_files
    : {};

  if (state === 'idle' || state === 'absent') {
    return (
      <Text fontSize="10.5px" color={colors.fg[4]}>
        Структурированный замысел появится после работы PDF-агента. Исходники можно
        редактировать как обычные .tex-файлы.
      </Text>
    );
  }

  if (state === 'loading' && !value) {
    return (
      <HStack role="status" color={colors.fg[4]}>
        <Spinner size="xs" />
        <Text fontSize="10.5px">Загружаю структуру документа…</Text>
      </HStack>
    );
  }

  if (!value) {
    return (
      <Text role="status" fontSize="10.5px" color={colors.warning}>
        Структура временно недоступна. LaTeX-исходники и редактор остаются доступны.
      </Text>
    );
  }

  return (
    <VStack align="stretch" spacing={2}>
      <BriefFacts intent={intent} draft={draft} />
      {state === 'stale' || state === 'unavailable' ? (
        <Text role="status" fontSize="10px" color={colors.warning}>
          Показана последняя полученная структура.
        </Text>
      ) : null}
      <HStack justify="space-between">
        <Text fontSize="10.5px" fontWeight="600" color={colors.fg[3]}>
          Структура · {blocks.length}
        </Text>
        <Text fontSize="10px" color={colors.fg[4]}>
          версия {Number(value.authoring_version || draft?.version || 0)}
        </Text>
      </HStack>
      <VStack align="stretch" spacing={1} maxH="220px" overflowY="auto">
        {blocks.map((block, index) => {
          const path = blockFiles[block.id || block.block_id];
          const label = block.title || block.text || `${safeBlock(block.kind)} ${index + 1}`;
          return (
            <Button
              key={block.id || block.block_id || index}
              variant="ghost"
              h="auto"
              minH="32px"
              px={2}
              py={1.5}
              justifyContent="flex-start"
              textAlign="left"
              whiteSpace="normal"
              isDisabled={!path}
              onClick={() => path && onOpenSource?.({ path })}
              aria-label={`${safeBlock(block.kind)}: ${label}`}
            >
              <Box minW={0}>
                <Text fontSize="10px" color={colors.fg[4]}>{safeBlock(block.kind)}</Text>
                <Text fontSize="11px" color={colors.fg[2]} noOfLines={2}>{label}</Text>
              </Box>
            </Button>
          );
        })}
      </VStack>
      <Box
        p={2}
        borderRadius={borderRadius.sm}
        border={`1px solid ${colors.border.subtle}`}
      >
        <Text fontSize="10px" color={colors.fg[4]}>
          Выберите блок, чтобы открыть его управляемый .tex-файл. Геометрия, класс
          документа и bibliography-команды остаются под контролем профиля.
        </Text>
      </Box>
    </VStack>
  );
}

export { safeBlock, safeKind };
