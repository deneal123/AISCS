import { render, screen } from '@testing-library/react';
import IdeAssistantResult from '@features/chat/components/IdeAssistantResult';

it('keeps a model report separate from a blocked verified-task result', () => {
  render(<IdeAssistantResult messages={[{ type: 'agent', metadata: {
    ide_summary: 'Скрипт создан.', task_result: {
      schema_version: 2, status: 'blocked', verified: false, blocker: 'verification_failed',
    },
  } }]} />);
  expect(screen.getByTestId('ide-task-result')).toHaveTextContent('Обязательная проверка не пройдена');
  expect(screen.getByTestId('ide-task-result')).not.toHaveTextContent('выполнена и проверена');
});

it('shows a concise report, not the full reply, separately from confirmed receipts', () => {
  const message = { type: 'agent', content: 'Длинный ответ с кодом', metadata: { ide_files_written: 0, ide_summary: 'Изучена структура проекта. Правки не потребовались.' } };
  const view = render(<IdeAssistantResult messages={[message]} />);
  expect(screen.getByTestId('ide-agent-summary')).toHaveTextContent(message.metadata.ide_summary);
  expect(screen.queryByText(message.content)).not.toBeInTheDocument();
  expect(screen.getByRole('status')).toHaveTextContent('Файлы в этом запросе не изменены.');
  view.rerender(<IdeAssistantResult messages={[{ ...message, metadata: { ide_files_written: 0, ide_write_unconfirmed: true } }]} />);
  expect(screen.getByRole('status')).toHaveTextContent('Результат записи не подтверждён');
  expect(screen.getByRole('status')).not.toHaveTextContent('записей в файлы нет');
});

it.each([undefined, '', 'x'.repeat(281), 'строка\nкод', 'Подтверждённых записей в файлы нет. Подробности запроса — в чате.', { summary: 'wrong' }])('never falls back to a long legacy reply for invalid summary %p', summary => {
  render(<IdeAssistantResult messages={[{ type: 'agent', content: 'Скрытый полный ответ', metadata: { ide_summary: summary } }]} />);
  expect(screen.getByTestId('ide-agent-summary')).toHaveTextContent('Краткий итог недоступен. Полный ответ — в чате.');
  expect(screen.queryByText('Скрытый полный ответ')).not.toBeInTheDocument();
});

it('renders the report literally, never as HTML or Markdown', () => {
  const summary = '<img src=x onerror=alert(1)> **Текст**';
  render(<IdeAssistantResult messages={[{ type: 'agent', metadata: { ide_summary: summary, ide_files_written: 2 } }]} />);
  expect(screen.getByTestId('ide-agent-summary')).toHaveTextContent(summary);
  expect(screen.queryByRole('img')).not.toBeInTheDocument();
  expect(screen.getByRole('status')).toHaveTextContent('Подтверждено записей в среду: 2');
});

it('counts Unicode code points like the server, not UTF-16 units', () => {
  const summary = '✅'.repeat(279) + '🚀';
  render(<IdeAssistantResult messages={[{ type: 'agent', metadata: { ide_summary: summary } }]} />);
  expect(screen.getByTestId('ide-agent-summary')).toHaveTextContent(summary);
});

it('uses the newer recovered result instead of an older retained live question', () => {
  render(<IdeAssistantResult messages={[
    { type: 'agent', timestamp: '2026-10-19T10:01:00Z', metadata: { ide_summary: 'Новый итог.' } },
    { type: 'agent', timestamp: '2026-10-19T10:00:00Z', metadata: { execution_status: 'waiting_user' } },
  ]} />);
  expect(screen.getByTestId('ide-agent-summary')).toHaveTextContent('Новый итог.');
});
