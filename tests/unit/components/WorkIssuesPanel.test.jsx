import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import { WorkIssuesPanel } from '@features/workspace-room/components/WorkIssuesPanel';

const renderPanel = (props = {}) => render(
  <ChakraProvider>
    <WorkIssuesPanel
      room={{ state: 'ready', issuesState: 'ready', issues: [] }}
      file={{ path: 'note.txt', revision: 'r1' }}
      busy=""
      onCreateIssue={jest.fn()}
      onUpdateIssue={jest.fn()}
      {...props}
    />
  </ChakraProvider>,
);

describe('WorkIssuesPanel', () => {
  it('validates title and the bounded line range before calling the API', () => {
    const onCreateIssue = jest.fn();
    renderPanel({ onCreateIssue });

    fireEvent.change(screen.getByLabelText('Строка от'), { target: { value: '8' } });
    fireEvent.change(screen.getByLabelText('Строка до'), { target: { value: '4' } });
    fireEvent.click(screen.getByRole('button', { name: 'Добавить задачу' }));

    expect(onCreateIssue).not.toHaveBeenCalled();
    expect(screen.getByText('Введите название задачи.')).toBeInTheDocument();
    expect(screen.getByText('Конечная строка не может быть меньше начальной.')).toBeInTheDocument();
    expect(screen.getByLabelText(/Новая задача для файла/)).toHaveFocus();
    expect(screen.getByLabelText('Строка до')).toHaveAttribute('aria-invalid', 'true');
  });

  it('keeps stale issue content and maps unknown status to a neutral label', () => {
    renderPanel({
      room: {
        state: 'ready',
        issuesState: 'stale',
        issues: [{
          issue_id: 'issue-1',
          title: 'Проверить',
          path: 'note.txt',
          start_line: 1,
          end_line: 2,
          status: 'future_status',
        }],
      },
    });

    expect(screen.getByText(/Показаны последние доступные задачи/i)).toBeInTheDocument();
    expect(screen.getByText('Проверить')).toBeInTheDocument();
    expect(screen.getByText('Статус недоступен')).toBeInTheDocument();
    expect(screen.queryByText('future_status')).not.toBeInTheDocument();
  });
});
