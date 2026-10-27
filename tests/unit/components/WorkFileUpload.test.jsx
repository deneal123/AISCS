import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import { WorkFileUpload } from '../../../src/features/workspace-room/components/WorkFileUpload';

describe('WorkFileUpload', () => {
  it('keeps the same focused control when cancellation becomes an explicit retry', async () => {
    const file = new File(['body'], 'notes.txt');
    const session = { start: jest.fn(), cancel: jest.fn(), state: 'uploading',
      selected: { file, intentId: 'same-intent', options: { libraryOnly: true } } };
    const view = render(<ChakraProvider><WorkFileUpload session={session} /></ChakraProvider>);
    const cancel = screen.getByRole('button', { name: 'Отменить', exact: true });
    act(() => cancel.focus());
    fireEvent.click(cancel);
    expect(session.cancel).toHaveBeenCalledTimes(1);
    view.rerender(<ChakraProvider><WorkFileUpload session={{ ...session, state: 'cancelled' }} /></ChakraProvider>);
    const retry = screen.getByRole('button', { name: 'Проверить и повторить', exact: true });
    expect(retry).toBe(cancel);
    expect(retry).toHaveFocus();
    fireEvent.click(retry);
    expect(session.start).toHaveBeenCalledWith(file, 'same-intent', { libraryOnly: true });
  });

  it('cannot bypass a disabled shared upload session through input or retry', () => {
    const start = jest.fn();
    const file = new File(['body'], 'notes.txt');
    render(<ChakraProvider><WorkFileUpload disabled session={{ start, state: 'error',
      selected: { file, intentId: 'same-intent' } }} /></ChakraProvider>);
    const input = screen.getByTestId('work-upload-input');
    expect(input).toBeDisabled();
    fireEvent.change(input, { target: { files: [file] } });
    const retry = screen.getByRole('button', { name: 'Проверить и повторить' });
    expect(retry).toBeDisabled(); fireEvent.click(retry);
    expect(start).not.toHaveBeenCalled();
  });
  it('reuses the same opaque intent after an uncertain result', async () => {
    const seen = [];
    const onUpload = jest.fn((_file, options) => {
      seen.push(options.uploadIntentId);
      return Promise.resolve(seen.length === 1 ? { ok: false, status: 503 } : { ok: true, outcome: 'imported' });
    });
    const rendered = render(<ChakraProvider><WorkFileUpload onUpload={onUpload} /></ChakraProvider>);
    const file = new File(['body'], 'brief.txt', { type: 'text/plain' });

    await act(async () => fireEvent.change(rendered.container.querySelector('input[type="file"]'), {
      target: { files: [file] },
    }));
    const retry = await screen.findByRole('button', { name: /Проверить и повторить/i });
    expect(screen.getByText('Статус не подтверждён. Проверьте библиотеку перед повтором. Повтор относится к той же загрузке.')).toBeInTheDocument();
    expect(rendered.container).not.toHaveTextContent(/upload[_ ]intent/i);
    await act(async () => fireEvent.click(retry));

    await waitFor(() => expect(onUpload).toHaveBeenCalledTimes(2));
    expect(seen[0]).toMatch(/^[0-9a-f-]{36}$/i);
    expect(seen[1]).toBe(seen[0]);
  });

  it('explains a changed-file conflict without exposing internal request terminology', async () => {
    const rendered = render(
      <ChakraProvider>
        <WorkFileUpload onUpload={() => Promise.resolve({ ok: false, status: 409 })} />
      </ChakraProvider>,
    );
    await act(async () => fireEvent.change(rendered.container.querySelector('input[type="file"]'), {
      target: { files: [new File(['changed body'], 'brief.txt')] },
    }));
    expect(await screen.findByText('Содержимое файла отличается от предыдущей попытки. Выберите файл заново.')).toBeInTheDocument();
    expect(screen.getByText('brief.txt')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Проверить и повторить/i })).not.toBeInTheDocument();
    expect(rendered.container).not.toHaveTextContent(/upload[_ ]intent/i);
  });

  it('reports a durable Library-only result as partial success, not a failed upload', async () => {
    const onPartial = jest.fn();
    const rendered = render(
      <ChakraProvider>
        <WorkFileUpload
          onUpload={() => Promise.resolve({ ok: true, outcome: 'library_saved' })}
          onPartial={onPartial}
        />
      </ChakraProvider>,
    );

    await act(async () => fireEvent.change(rendered.container.querySelector('input[type="file"]'), {
      target: { files: [new File(['body'], 'brief.txt')] },
    }));

    expect(await screen.findByText(/Источник сохранён в библиотеке/i)).toBeInTheDocument();
    expect(onPartial).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/Файл не добавлен/i)).not.toBeInTheDocument();
  });

  it('does not cancel a committed upload when only its visual control unmounts', async () => {
    let finishUpload;
    let uploadSignal;
    const onUpload = jest.fn((_file, options) => {
      uploadSignal = options.signal;
      return new Promise((resolve) => { finishUpload = resolve; });
    });
    const rendered = render(
      <ChakraProvider><WorkFileUpload onUpload={onUpload} /></ChakraProvider>,
    );

    await act(async () => fireEvent.change(rendered.container.querySelector('input[type="file"]'), {
      target: { files: [new File(['body'], 'brief.txt')] },
    }));
    await waitFor(() => expect(onUpload).toHaveBeenCalledTimes(1));

    rendered.unmount();
    expect(uploadSignal.aborted).toBe(false);
    await act(async () => finishUpload({ ok: true, outcome: 'imported' }));
  });
});
