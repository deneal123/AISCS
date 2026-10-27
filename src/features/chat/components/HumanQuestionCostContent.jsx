import { Button, Text } from '@chakra-ui/react';
import AppLoading from '@shared/controls/AppLoading';
import { colors } from '@theme/tokens';

export function QuestionCostDetails({ cost }) {
  return <>
    {cost.phase === 'cost_loading' ? <AppLoading label="Проверяю стоимость…" /> : <>
      {!cost.stop?.requested &&
      <Text mt={2} fontSize="12px" color={colors.fg[3]} sx={{ '@media (max-height: 400px)': { display: 'none' } }}>
        {cost.phase === 'cost_expired' ? 'Срок оценки истёк. Обновите её, чтобы продолжить.'
          : ['cost_unknown', 'cost_unavailable', 'cost_blocked'].includes(cost.phase) ? 'Ответ сохранён. Состояние продолжения нужно проверить.'
          : 'Ответ сохранён. Продолжение ждёт вашего решения о стоимости.'}
      </Text>}
      {cost.error && <Text mt={2} fontSize="12px" color={colors.warning} role="alert">{cost.error}</Text>}
    </>}
  </>;
}

export function QuestionCostActions({ cost, action, cancelRef }) {
  const button = { ...action, h: '44px', minH: '44px', py: 1, fontSize: '12px', lineHeight: 1.3 };
  const checking = ['cost_loading', 'cost_unknown', 'cost_unavailable', 'cost_blocked'].includes(cost.phase);
  const stopping = Boolean(cost.stop?.requested);
  const offerStop = Boolean(cost.stop) && (stopping || ['cost_loading', 'cost_unknown', 'cost_unavailable'].includes(cost.phase));
  const decision = cost.retry || (cost.phase === 'cost_expired' ? 'refresh' : 'accept');
  const label = decision === 'refresh' ? 'Обновить оценку'
    : decision === 'decline' ? 'Повторить отказ'
      : cost.retry ? 'Повторить решение' : 'Подтвердить запуск';
  return <>
    <Button {...button} ref={cancelRef} type="button" variant="ghost"
      isDisabled={Boolean(cost.busy) || (!offerStop && ((checking && cost.phase !== 'cost_blocked') || (Boolean(cost.retry) && cost.retry !== 'decline')))}
      onClick={() => offerStop ? cost.stop.stop() : cost.decide('decline')}>{offerStop ? stopping ? 'Повторить остановку' : 'Остановить' : 'Не запускать'}</Button>
    {checking || stopping ? <Button {...button} type="button" variant="workbenchSecondary"
      isDisabled={cost.phase === 'cost_loading' || Boolean(cost.busy)} onClick={cost.refresh}>Проверить состояние</Button>
      : <Button {...button} type="button" variant={decision === 'accept' ? 'workbenchPrimary' : 'workbenchSecondary'}
        isLoading={Boolean(cost.busy)} isDisabled={Boolean(cost.busy)} onClick={() => cost.decide(decision)}>{label}</Button>}
  </>;
}
