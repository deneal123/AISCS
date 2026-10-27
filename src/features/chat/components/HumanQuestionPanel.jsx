import { useEffect, useId, useLayoutEffect, useRef } from 'react';
import { Box, Button, Flex, FormControl, FormLabel, HStack, Text, VStack } from '@chakra-ui/react';
import AppLoading from '@shared/controls/AppLoading';
import AppTextarea from '@shared/controls/AppTextarea';
import { colors } from '@theme/tokens';
import { QuestionCostActions, QuestionCostDetails } from './HumanQuestionCostContent';

/** A bounded workbench state, not another modal/composer/trace owner. */
export default function HumanQuestionPanel({ state, ideMode, onStop }) {
  const heading = useRef(null);
  const cancelRef = useRef(null);
  const id = useId();
  useEffect(() => {
    if (document.activeElement === document.body || document.activeElement?.closest('[data-composer-container], [data-testid="document-assistant-activity"]')) {
      heading.current?.focus({ preventScroll: true });
    }
  }, [state.question?.question_id]);
  useLayoutEffect(() => {
    if (state.costMode && (document.activeElement === document.body
      || document.activeElement?.closest('[data-testid="human-question-panel"]'))) {
      const target = cancelRef.current && !cancelRef.current.disabled ? cancelRef.current : heading.current;
      target?.focus({ preventScroll: true });
    }
  }, [state.costMode, state.cost?.phase, state.cost?.view?.offer_id]);
  const unresolved = ['unknown', 'unavailable'].includes(state.phase);
  const question = state.verified === false ? null : state.question;
  const action = { size: 'document', minH: '44px', h: 'auto', py: 2, minW: 0, flex: 1, whiteSpace: 'normal' };
  return <Flex as="form" noValidate onSubmit={event => { event.preventDefault(); if (!state.costMode && !event.nativeEvent?.isComposing) state.submit(); }}
    role="region" aria-label={state.costMode ? 'Подтверждение стоимости' : 'Вопрос агента'} data-testid="human-question-panel" direction="column" minH={0} minW={0}
    flex={ideMode ? '1' : undefined} h={ideMode ? 'full' : 'min(360px, 42dvh)'} overflow="hidden">
    <Box flex="1" minH={0} overflowY="auto" overscrollBehavior="contain" px={3} pt={3} pb={2}
      role="region" aria-label="Детали продолжения" tabIndex={0}
      _focusVisible={{ outline: `2px solid ${colors.border.focus}`, outlineOffset: '-2px' }}>
      {!state.costMode && <Text color={colors.fg[3]} fontSize="11px" mb={1}>Нужен ваш ответ</Text>}
      <Text as="h3" ref={heading} tabIndex={-1} fontSize={state.costMode ? '16px' : '13px'} fontWeight={600} whiteSpace="pre-wrap"
        position={state.costMode ? 'sticky' : undefined} top={state.costMode ? 0 : undefined} zIndex={state.costMode ? 1 : undefined}
        bg={state.costMode ? ideMode ? colors.bg.card : colors.ink[950] : undefined}
        _focusVisible={{ outline: `2px solid ${colors.border.focus}`, outlineOffset: '2px' }}>{state.costMode
          ? state.cost.stop?.requested ? 'Остановка продолжения' : state.cost.view ? `До ${state.cost.view.estimated_credits.toLocaleString('ru-RU')} кредитов` : 'Проверяю стоимость'
          : question?.prompt || 'Вопрос агента'}</Text>
      {state.costMode ? <QuestionCostDetails cost={state.cost} /> : state.phase === 'loading' ? <AppLoading label="Проверяю вопрос…" />
        : state.phase === 'child_unavailable' ? <Text mt={3} role="alert" fontSize="12px" color={colors.warning}>{state.error}</Text>
          : <>
            <VStack mt={3} align="stretch" spacing={1} role="group" aria-label="Варианты ответа">
              {(question?.choices || []).map(choice => <Button key={choice.id} size="document" minH="44px" h="auto" py={2}
                textAlign="left" whiteSpace="normal" justifyContent="flex-start" variant={state.draft.choice === choice.id ? 'workbenchPrimary' : 'workbenchSecondary'}
                aria-pressed={state.draft.choice === choice.id} isDisabled={state.locked || unresolved}
                onClick={() => state.setChoice(choice.id)}>{choice.label}</Button>)}
            </VStack>
            <FormControl mt={3}>
              <FormLabel htmlFor={`${id}-answer`} fontSize="12px" mb={1}>Свой ответ или детали</FormLabel>
              <AppTextarea id={`${id}-answer`} value={state.draft.text} onChange={event => state.setText(event.target.value)}
                isReadOnly={state.locked || unresolved} maxLength={4000} rows={3} resize="none" fontSize="13px" minH="76px"
                aria-describedby={state.error ? `${id}-error` : undefined} />
            </FormControl>
            {state.error && <Text id={`${id}-error`} role="alert" mt={2} fontSize="12px" color={colors.warning}>{state.error}</Text>}
            {state.retrying && !state.busy && !state.error && <Text mt={2} fontSize="12px" color={colors.fg[3]}>Повторная отправка сохранит тот же ответ.</Text>}
            {!state.targetReady && <Text mt={2} fontSize="12px" color={colors.fg[3]}>Для ответа нужен доступный проект, в котором агент задал вопрос.</Text>}
          </>}
    </Box>
    <HStack flexShrink={0} px={3} py={2} spacing={2} justify="flex-end" borderTop="1px solid" borderColor={colors.border.subtle}>
      {state.costMode ? <QuestionCostActions cost={state.cost} action={action} cancelRef={cancelRef} /> : state.phase === 'child_unavailable' ? <>
        <Button {...action} variant="ghost" onClick={onStop}>Остановить</Button>
        <Button {...action} variant="workbenchPrimary" onClick={state.checkChild}>Проверить продолжение</Button>
      </> : <>
        <Button {...action} variant="ghost" isDisabled={Boolean(state.busy)} onClick={state.cancel}>Не продолжать</Button>
        {unresolved ? <Button {...action} variant="workbenchSecondary" isDisabled={Boolean(state.busy)} onClick={state.refresh}>Проверить состояние</Button>
          : <Button {...action} variant="workbenchPrimary" type="submit" isLoading={state.busy === 'answer'}
            isDisabled={state.phase !== 'pending' || !state.targetReady || (!state.draft.choice && !state.draft.text.trim()) || state.busy === 'cancel'}>{state.retrying && !state.busy ? 'Повторить ответ' : 'Продолжить'}</Button>}
      </>}
    </HStack>
  </Flex>;
}
