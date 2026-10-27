import { memo, useId, useRef } from 'react';
import { Box, Button, HStack, Modal, ModalBody, ModalCloseButton, ModalContent, ModalFooter, ModalHeader,
  ModalOverlay, SimpleGrid, Text } from '@chakra-ui/react';
import AppLoading from '@shared/controls/AppLoading';
import { colors } from '@theme/tokens';
import { usePdfProposalReview } from '../model/usePdfProposalReview';
import { proposalBlockName, proposalBlockText } from '../model/pdfProposal';

export { proposalBlockText } from '../model/pdfProposal';

const CHANGE_LABELS = { insert: 'Добавление', delete: 'Удаление', move: 'Перемещение',
  replace: 'Изменение', replace_move: 'Изменение и перемещение' };

function ProposalBlock({ block, empty }) {
  if (!block) return <Text fontSize="13px" color={colors.fg[3]}>{empty}</Text>;
  return <>
    <Text fontSize="11px" color={colors.fg[3]} mb={1}>{proposalBlockName(block)}
      {block.kind === 'section' ? ' · уровень ' + (block.level || 1) : ''}</Text>
    <Text fontSize="13px" lineHeight={1.6} whiteSpace="pre-wrap" overflowWrap="anywhere"
      fontFamily={['table', 'equation'].includes(block.kind) ? 'mono' : undefined}>{proposalBlockText(block)}</Text>
  </>;
}

const PdfProposalComparison = memo(function PdfProposalComparison({ before, after, index, kind, fromIndex, toIndex }) {
  const block = after || before;
  const moved = kind === 'move' || kind === 'replace_move';
  return <Box as="section" aria-label={'Изменение ' + (index + 1)} py={3}
    borderTop="1px solid" borderColor={colors.border.subtle}>
    <Text fontWeight={600} fontSize="13px" mb={2} overflowWrap="anywhere">{block.title || proposalBlockName(block)}</Text>
    {kind && <Text fontSize="12px" color={colors.fg[3]} mb={2}>
      {CHANGE_LABELS[kind]}{moved ? ` · позиция ${fromIndex + 1} → ${toIndex + 1}`
        : kind === 'insert' ? ` · новая позиция ${toIndex + 1}` : kind === 'delete' ? ` · позиция ${fromIndex + 1}` : ''}
    </Text>}
    {!before || !after ? <Box>
      <Text fontSize="12px" color={colors.fg[3]} mb={2}>{before ? 'Блок будет удалён' : 'Блока не было'}</Text>
      <Text fontSize="11px" fontWeight={600} color={colors.fg[3]}>{before ? 'Было' : 'Предложено'}</Text>
      <ProposalBlock block={block} />
    </Box> : kind === 'move' ? <ProposalBlock block={block} /> : <SimpleGrid columns={{ base: 1, md: 2 }} spacing={3}>
      {[[before, 'Было'], [after, 'Предложено']].map(([block, label]) => <Box key={label} minW={0}>
        <Text fontSize="11px" fontWeight={600} color={label === 'Предложено' ? colors.blue[100] : colors.fg[3]}>{label}</Text>
        <ProposalBlock block={block} empty={label === 'Было' ? 'Блока не было' : 'Блок будет удалён'} />
      </Box>)}
    </SimpleGrid>}
  </Box>;
});

/** Protected block replacements, with library-owned modal focus and scroll. */
export function PdfProposalReview(props) {
  const { active, project, proposalId, dirty } = props;
  const review = usePdfProposalReview(props);
  const summaryId = useId();
  const trigger = useRef(null);
  const closeButton = useRef(null);
  const outcomeRef = useRef(null);
  if (!active || !project?.path || !proposalId) return null;
  const applying = review.busy === 'apply';
  return <>
    {review.outcome ? <Box ref={outcomeRef} tabIndex={-1} role="status" fontSize="12px" color={colors.fg[3]}>
      {review.outcome.text}
      {review.outcome.refreshFailed && <Button size="workbench" variant="ghost" isDisabled={dirty}
        isLoading={review.busy === 'refresh'} onClick={review.retryRefresh}>Обновить документ</Button>}
      {review.outcome.refreshFailed && dirty && <Text>Сначала сохраните или отмените ручные изменения.</Text>}
    </Box> : <Button ref={trigger} size="workbench" variant="workbenchSecondary" onClick={review.review}>Посмотреть изменения</Button>}
    <Modal isOpen={review.open} onClose={review.close} initialFocusRef={closeButton} finalFocusRef={review.outcome ? outcomeRef : trigger}
      closeOnEsc={!applying} closeOnOverlayClick={!applying} motionPreset="none" size="4xl">
      <ModalOverlay /><ModalContent bg={colors.ink[900]} mx={3} my={4} overflow="hidden" aria-describedby={summaryId}>
        <ModalHeader pr={10} pb={2} flexShrink={0} fontSize="16px">Предлагаемые изменения</ModalHeader>
        <ModalCloseButton aria-label="Закрыть просмотр правок" isDisabled={applying} />
        <ModalBody minH="160px" overflowY="auto" px={{ base: 3, md: 5 }} pb={3} tabIndex={0}
          role="region" aria-label="Сравнение версий документа"
          _focusVisible={{ outline: `2px solid ${colors.border.focus}`, outlineOffset: '-2px' }}>
          <Text id={summaryId} fontSize="12px" color={colors.fg[3]} mb={3}>
            {review.value?.stale ? 'Базовая версия изменилась. Нужно новое предложение, а не повторное применение.'
              : review.value ? review.changed.length ? 'Изменено фрагментов: ' + review.changed.length + '. Остальные блоки сохранятся.'
              : 'В предложении нет отличий от текущего документа.' : 'Просмотрите изменения перед применением к документу.'}
          </Text>
          {review.busy === 'read' && <AppLoading label="Загружаю правки…" />}
          {review.error && <Text role="alert" color={colors.warning}>{review.error}</Text>}
          {review.value?.stale && <Text role="status" color={colors.warning}>Предложение устарело. Применение заблокировано.</Text>}
          {dirty && <Text role="status" color={colors.warning}>Сначала сохраните или отмените ручные изменения.</Text>}
          {review.changed.map((change, index) => <PdfProposalComparison
            key={(change.after || change.before).block_id} {...change} index={index} />)}
        </ModalBody>
        <ModalFooter borderTop="1px solid" borderColor={colors.border.subtle} flexShrink={0}
          px={{ base: 3, md: 5 }} py={3} pb="max(12px, env(safe-area-inset-bottom))">
          <HStack w="full" flexWrap="wrap" spacing={2} rowGap={2}>
            <Button ref={closeButton} size="workbench" variant="workbenchSecondary" isDisabled={applying} onClick={review.close}>Закрыть</Button>
            <Button size="workbench" variant="ghost" isDisabled={Boolean(review.busy) || !review.value} onClick={review.reject}>Отклонить</Button>
            <Button size="workbench" variant="ghost" isDisabled={Boolean(review.busy)} onClick={review.review}>Обновить просмотр</Button>
            <Button size="workbench" variant="workbenchPrimary" ml="auto" isLoading={applying}
              isDisabled={!review.value || review.value.stale || dirty || Boolean(review.error) || !review.changed.length}
              onClick={review.apply}>Применить</Button>
          </HStack>
        </ModalFooter>
      </ModalContent>
    </Modal>
  </>;
}
