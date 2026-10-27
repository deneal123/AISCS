import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import { WorkIssuesPanel } from '@features/workspace-room/components/WorkIssuesPanel';
import { useWorkIssueDraft } from '@features/workspace-room/model/useWorkIssueDraft';

function DraftOwner({ layout = 'rail', threadId = 'thread', path = 'note.txt', onCreateIssue }) {
  const draft = useWorkIssueDraft(threadId, path);
  return <ChakraProvider><WorkIssuesPanel key={layout} draft={draft}
    room={{ issues: [] }} file={{ path }} busy="" onCreateIssue={onCreateIssue}
    onUpdateIssue={jest.fn()} /></ChakraProvider>;
}

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
  it('retains fields and validation when responsive instances are replaced', () => {
    const view = render(<DraftOwner />);
    fireEvent.change(screen.getByLabelText(/Новая задача для файла/), {
      target: { value: 'Draft title' },
    });
    fireEvent.change(screen.getByLabelText('Контекст'), { target: { value: 'Draft body' } });
    fireEvent.change(screen.getByLabelText('Строка от'), { target: { value: '8' } });
    fireEvent.change(screen.getByLabelText('Строка до'), { target: { value: '4' } });
    fireEvent.click(screen.getByRole('button', { name: 'Добавить задачу' }));
    for (const layout of ['drawer', 'mobile', 'rail']) {
      view.rerender(<DraftOwner layout={layout} />);
      expect(screen.getByLabelText(/Новая задача для файла/)).toHaveValue('Draft title');
      expect(screen.getByLabelText('Контекст')).toHaveValue('Draft body');
      expect(screen.getByLabelText('Строка до')).toHaveValue(4);
      expect(screen.getByLabelText('Строка до')).toHaveAttribute('aria-invalid', 'true');
    }
  });

  it('a save acknowledgement cannot clear newer input in the replacement panel', async () => {
    let complete;
    const onCreateIssue = jest.fn(() => new Promise((resolve) => { complete = resolve; }));
    const view = render(<DraftOwner onCreateIssue={onCreateIssue} />);
    fireEvent.change(screen.getByLabelText(/Новая задача для файла/), {
      target: { value: 'Submitted title' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Добавить задачу' }));
    view.rerender(<DraftOwner layout="drawer" onCreateIssue={onCreateIssue} />);
    fireEvent.change(screen.getByLabelText(/Новая задача для файла/), {
      target: { value: 'Newer title' },
    });
    await act(async () => complete(true));
    expect(screen.getByLabelText(/Новая задача для файла/)).toHaveValue('Newer title');
    expect(onCreateIssue).toHaveBeenCalledTimes(1);
  });

  it('clears only the submitted form after success, including after remount', async () => {
    let complete;
    const onCreateIssue = jest.fn(() => new Promise((resolve) => { complete = resolve; }));
    const view = render(<DraftOwner onCreateIssue={onCreateIssue} />);
    fireEvent.change(screen.getByLabelText(/Новая задача для файла/), {
      target: { value: 'Submitted title' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Добавить задачу' }));
    view.rerender(<DraftOwner layout="mobile" onCreateIssue={onCreateIssue} />);
    await act(async () => complete(true));
    expect(screen.getByLabelText(/Новая задача для файла/)).toHaveValue('');
  });

  it.each(['path', 'threadId'])('does not carry a draft to another %s', (field) => {
    const view = render(<DraftOwner />);
    fireEvent.change(screen.getByLabelText(/Новая задача для файла/), {
      target: { value: 'Old scope' },
    });
    view.rerender(<DraftOwner {...{ [field]: 'new-scope' }} />);
    expect(screen.getByLabelText(/Новая задача для файла/)).toHaveValue('');
    view.rerender(<DraftOwner />);
    expect(screen.getByLabelText(/Новая задача для файла/)).toHaveValue('');
  });

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
