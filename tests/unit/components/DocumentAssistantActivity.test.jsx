import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import DocumentAssistantActivity from '@features/chat/components/DocumentAssistantActivity';
import theme from '../../../src/theme';
import { presentTaskResult } from '@features/chat/model/taskResult';

jest.mock('@features/chat/components/trace/TracePanel', () => (props) => <div>
  <span>{props.sessions[0].events[0]?.title}</span>
  <button onClick={() => props.onRunMode?.({ offer_id: 'same-offer' })}>Решение по исходному offer</button>
  <button onClick={() => props.onToggleExpanded(props.sessions[0].id, false)}>Свернуть трейс</button>
  <span>{props.expandedMap[props.sessions[0].id] ? 'Трейс раскрыт' : 'Трейс свёрнут'}</span>
</div>);

const session = { id: 's1', status: 'running', events: [{ title: 'Сохраняю изменения в проекте' }] };
const state = { session, anchor: { id: 'user-1', content: 'Правка' }, tracing: true, running: true };

it('shows the task blocker even though its trace transport is done', () => {
  const taskResult = presentTaskResult({
    schema_version: 2, status: 'blocked', verified: false, blocker: 'verification_unavailable',
  });
  render(<ChakraProvider theme={theme}><DocumentAssistantActivity
    state={{ ...state, taskResult, tracing: false, running: false, session: { ...session, status: 'done' } }}
    messages={{}} /></ChakraProvider>);
  expect(screen.getByRole('status')).toHaveTextContent('Задача заблокирована');
  expect(screen.getByRole('status')).toHaveTextContent('Обязательная проверка недоступна');
  expect(screen.getByRole('status')).not.toHaveTextContent('Запрос завершён');
  expect(screen.queryByRole('button', { name: 'Остановить генерацию' })).not.toBeInTheDocument();
});

it('shows the existing trace and Stop instead of a separate response pipeline', async () => {
  const onStop = jest.fn();
  const onRunMode = jest.fn();
  render(<ChakraProvider theme={theme}><DocumentAssistantActivity state={state} messages={{ onRunMode }} onStop={onStop} /></ChakraProvider>);
  expect(await screen.findByText('Сохраняю изменения в проекте')).toBeVisible();
  expect(screen.getByRole('button', { name: 'Остановить генерацию' })).toHaveStyle({ height: '34px' });
  fireEvent.click(screen.getByRole('button', { name: 'Остановить генерацию' }));
  expect(onStop).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'Решение по исходному offer' }));
  expect(onRunMode).toHaveBeenCalledWith({ offer_id: 'same-offer' }, 'Правка', 'user-1', 's1');
});

it('uses one completed disclosure state and releases its height when the trace is collapsed', async () => {
  render(<ChakraProvider theme={theme}><DocumentAssistantActivity variant="ide" state={{ ...state, tracing: false, running: false,
    session: { ...session, status: 'done' } }} messages={{ tracePanelsExpanded: { s1: false } }} /></ChakraProvider>);
  expect(screen.getByRole('status')).toHaveTextContent(/^Запрос завершён\.$/);
  fireEvent.click(screen.getByRole('button', { name: 'Этапы', exact: true }));
  expect(await screen.findByText('Трейс раскрыт')).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Свернуть трейс' }));
  expect(screen.queryByText('Трейс раскрыт')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Этапы', exact: true })).toHaveAttribute('aria-expanded', 'false');
  expect(screen.getByRole('region', { name: 'Выполнение запроса IDE' }).style.height).toBe('');
});

it('keeps completion bounded, with an explicit Chat action and optional trace', async () => {
  const onOpenChat = jest.fn();
  render(<ChakraProvider theme={theme}><DocumentAssistantActivity state={{ ...state, tracing: false, running: false,
    session: { ...session, status: 'done' } }} messages={{}} onOpenChat={onOpenChat} /></ChakraProvider>);
  expect(screen.queryByText('Сохраняю изменения в проекте')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Этапы', exact: true })).toHaveStyle({ height: '34px' });
  expect(screen.getByRole('button', { name: 'Открыть в Чате' })).toHaveStyle({ height: '34px' });
  fireEvent.click(screen.getByRole('button', { name: 'Этапы', exact: true }));
  expect(await screen.findByText('Сохраняю изменения в проекте')).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Открыть в Чате' }));
  expect(onOpenChat).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole('button', { name: 'Остановить генерацию' })).not.toBeInTheDocument();
});
