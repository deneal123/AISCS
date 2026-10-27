import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import ChatMemoryDrawer from '../../../src/features/chat/components/drawers/ChatMemoryDrawer';

function show(props = {}) {
  return render(<ChakraProvider><ChatMemoryDrawer isOpen onClose={() => {}}
    memoryFacts={[]} onAddFact={jest.fn()} onSearch={jest.fn()} {...props} /></ChakraProvider>);
}

it('показывает компактное пустое состояние и одно действие добавления', () => {
  show();
  expect(screen.getByText('Пока нет фактов')).toBeVisible();
  expect(screen.getAllByRole('button', { name: 'Добавить факт', exact: true })).toHaveLength(1);
  expect(screen.queryByLabelText('Добавить факт вручную')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Добавить факт', exact: true }));
  expect(screen.getByLabelText('Добавить факт вручную')).toHaveFocus();
  expect(screen.getByRole('button', { name: 'Сохранить факт', exact: true })).toBeDisabled();
});

it('при отмене сохраняет черновик и возвращает фокус', () => {
  show();
  const add = screen.getByRole('button', { name: 'Добавить факт', exact: true });
  fireEvent.click(add);
  fireEvent.change(screen.getByLabelText('Добавить факт вручную'), { target: { value: 'Важное' } });
  fireEvent.click(screen.getByRole('button', { name: 'Отмена', exact: true }));
  expect(add).toHaveFocus();
  fireEvent.click(add);
  expect(screen.getByLabelText('Добавить факт вручную')).toHaveValue('Важное');
});

it('после ошибки оставляет форму и текст, не сообщает об успехе', async () => {
  const onAddFact = jest.fn().mockResolvedValue(false);
  show({ onAddFact });
  fireEvent.click(screen.getByRole('button', { name: 'Добавить факт', exact: true }));
  fireEvent.change(screen.getByLabelText('Добавить факт вручную'), { target: { value: 'Важное' } });
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Сохранить факт', exact: true })));
  expect(screen.getByRole('alert')).toHaveTextContent('Не удалось сохранить факт');
  expect(screen.getByLabelText('Добавить факт вручную')).toHaveValue('Важное');
});

it('быстрые повторные отправки не дублируют сохранение', async () => {
  let resolve;
  const onAddFact = jest.fn(() => new Promise(done => { resolve = done; }));
  show({ onAddFact });
  fireEvent.click(screen.getByRole('button', { name: 'Добавить факт', exact: true }));
  const input = screen.getByLabelText('Добавить факт вручную');
  fireEvent.change(input, { target: { value: 'Первая строка\nВторая строка' } });
  act(() => { fireEvent.submit(input.closest('form')); fireEvent.submit(input.closest('form')); });
  expect(onAddFact).toHaveBeenCalledTimes(1);
  await act(async () => resolve(true));
  expect(screen.queryByLabelText('Добавить факт вручную')).not.toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole('button', { name: 'Добавить факт', exact: true })).toHaveFocus());
});

it('не называет всю память пустой, когда есть резюме разговоров', () => {
  show({ memoryDashboard: { text_mem: [{ memories: ['Резюме диалога'] }] } });
  expect(screen.getByText('Резюме разговоров доступны ниже.')).toBeVisible();
  expect(screen.getByText('Резюме диалога')).toBeVisible();
});
