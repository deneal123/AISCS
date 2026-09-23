import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import { WorkFileUpload } from '../../../src/features/workspace-room/components/WorkFileUpload';

describe('WorkFileUpload', () => {
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
    await act(async () => fireEvent.click(retry));

    await waitFor(() => expect(onUpload).toHaveBeenCalledTimes(2));
    expect(seen[0]).toMatch(/^[0-9a-f-]{36}$/i);
    expect(seen[1]).toBe(seen[0]);
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
