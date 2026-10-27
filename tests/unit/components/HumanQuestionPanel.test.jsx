import { fireEvent, render, screen } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import HumanQuestionPanel from '@features/chat/components/HumanQuestionPanel';

function state(update = {}) {
  return { question: { question_id: 'q', prompt: 'Какую структуру создать?', choices: [{ id: 'small', label: 'Минимальная' }, { id: 'full', label: 'Полная' }] },
    phase: 'pending', draft: { choice: null, text: '' }, busy: '', targetReady: true,
    submit: jest.fn(), cancel: jest.fn(), refresh: jest.fn(), setChoice: jest.fn(), setText: jest.fn(), ...update };
}
function mount(value) { return render(<ChakraProvider><HumanQuestionPanel state={value} /></ChakraProvider>); }

test('offers compact pressed choices and a labelled free-text alternative, not checkboxes', () => {
  const value = state(); mount(value);
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Продолжить' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Минимальная' }));
  expect(value.setChoice).toHaveBeenCalledWith('small');
  fireEvent.change(screen.getByLabelText('Свой ответ или детали'), { target: { value: 'Свой ответ' } });
  expect(value.setText).toHaveBeenCalledWith('Свой ответ');
  expect(screen.getByRole('region', { name: 'Вопрос агента' })).toHaveAttribute('novalidate');
});

test('unknown completion retains readable input and offers a read, not another submit', () => {
  const value = state({ phase: 'unknown', locked: true, draft: { text: 'Не потерять', choice: 'small' }, error: 'Ответ не подтверждён' });
  mount(value);
  expect(screen.getByLabelText('Свой ответ или детали')).toHaveValue('Не потерять');
  expect(screen.getByLabelText('Свой ответ или детали')).toHaveAttribute('readonly');
  expect(screen.queryByRole('button', { name: 'Продолжить' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Проверить состояние' }));
  expect(value.refresh).toHaveBeenCalledTimes(1); expect(value.submit).not.toHaveBeenCalled();
});

test('cost consent reuses the inline frame, focuses decline and cannot be submitted by the answer form', () => {
  const cost = { phase: 'cost_pending', view: { offer_id: 'quote', estimated_credits: 5000 }, decide: jest.fn(), refresh: jest.fn() };
  const value = state({ phase: 'cost_pending', costMode: true, cost }); mount(value);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(screen.getByRole('region', { name: 'Детали продолжения' })).toHaveAttribute('tabindex', '0');
  expect(screen.getByText('До 5 000 кредитов')).toBeVisible();
  expect(screen.getByRole('button', { name: 'Не запускать' })).toHaveFocus();
  fireEvent.submit(screen.getByRole('region', { name: 'Подтверждение стоимости' }));
  expect(cost.decide).not.toHaveBeenCalled(); expect(value.submit).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Подтвердить запуск' }));
  expect(cost.decide).toHaveBeenCalledWith('accept');
});

test.each(['cost_expired', 'cost_unknown'])('cost recovery %s never sends an automatic paid decision', phase => {
  const cost = { phase, view: { estimated_credits: 5000 }, decide: jest.fn(), refresh: jest.fn(), error: phase === 'cost_unknown' ? 'Результат неизвестен' : '' };
  mount(state({ phase, costMode: true, cost }));
  const label = phase === 'cost_expired' ? 'Обновить оценку' : 'Проверить состояние';
  fireEvent.click(screen.getByRole('button', { name: label }));
  if (phase === 'cost_expired') expect(cost.decide).toHaveBeenCalledWith('refresh');
  else {
    expect(cost.decide).not.toHaveBeenCalled(); expect(cost.refresh).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: 'Не запускать' })).toBeDisabled();
  }
});

test('unknown cost and Stop reuse the same two fixed action slots without a paid submit', () => {
  const stop = { stop: jest.fn(), requested: false };
  const cost = { phase: 'cost_unknown', view: { estimated_credits: 5000 }, stop, refresh: jest.fn(), decide: jest.fn() };
  const view = mount(state({ phase: cost.phase, costMode: true, cost }));
  fireEvent.click(screen.getByRole('button', { name: 'Остановить', exact: true }));
  expect(stop.stop).toHaveBeenCalledTimes(1); expect(cost.decide).not.toHaveBeenCalled();
  view.rerender(<ChakraProvider><HumanQuestionPanel state={state({ costMode: true,
    cost: { ...cost, phase: 'cost_stop_unknown', stop: { ...stop, requested: true } },
  })} /></ChakraProvider>);
  expect(screen.getByRole('heading', { name: 'Остановка продолжения' })).toBeVisible();
  expect(screen.queryByText(/ждёт вашего решения/)).not.toBeInTheDocument();
  expect(screen.getAllByRole('button')).toHaveLength(2);
  fireEvent.click(screen.getByRole('button', { name: 'Проверить состояние', exact: true }));
  expect(cost.refresh).toHaveBeenCalledTimes(1);
});

test('a loading cost read does not disable the owned same-child Stop', () => {
  const stop = { stop: jest.fn(), requested: false };
  const cost = { phase: 'cost_loading', view: null, stop, refresh: jest.fn(), decide: jest.fn() };
  mount(state({ phase: cost.phase, costMode: true, cost }));
  const button = screen.getByRole('button', { name: 'Остановить', exact: true });
  expect(button).toBeEnabled();
  fireEvent.click(button);
  expect(stop.stop).toHaveBeenCalledTimes(1); expect(cost.decide).not.toHaveBeenCalled();
});
