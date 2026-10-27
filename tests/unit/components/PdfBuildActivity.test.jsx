import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import { PdfBuildActivity } from '@features/workspace-room/components/PdfBuildActivity';
import { PdfPreviewButton } from '@features/workspace-room/components/PdfPreviewButton';

const ui = (document, onOpenPdf = jest.fn()) => <ChakraProvider>
  <PdfPreviewButton document={document} onOpenPdf={onOpenPdf} />
  <PdfBuildActivity document={document} />
</ChakraProvider>;

it.each([
  ['queued', 'Сборка PDF в очереди'], ['preparing', 'Подготавливаю PDF…'],
  ['building', 'Собираю PDF…'], ['deterministic_audit', 'Техническая проверка PDF…'],
  ['visual_audit', 'Визуальная проверка PDF…'], ['publishing', 'Сохраняю PDF…'],
])('exposes %s without opening checks or claiming completion', (state, text) => {
  render(ui({ build: { state } }));
  expect(screen.getByRole('status')).toHaveTextContent(text);
  expect(screen.queryByRole('button', { name: 'Открыть PDF' })).not.toBeInTheDocument();
});

it('covers admission before a build id exists and explicit cancellation', () => {
  const view = render(ui({ busy: 'build' }));
  expect(screen.getByRole('status')).toHaveTextContent('Запускаю сборку PDF…');
  view.rerender(ui({ busy: 'cancel', build: { state: 'building' } }));
  expect(screen.getByRole('status')).toHaveTextContent('Отменяю сборку…');
});

it('keeps opening and retry outside the disclosure without another compilation', () => {
  const open = jest.fn();
  render(ui({ build: { state: 'preview_ready', artifacts: [{ role: 'pdf' }] }, previewError: true }, open));
  expect(screen.getByRole('status')).toHaveTextContent('Черновик готов');
  expect(screen.getByRole('alert')).toHaveTextContent('Не удалось открыть превью');
  fireEvent.click(screen.getByRole('button', { name: 'Открыть PDF' }));
  expect(open).toHaveBeenCalledTimes(1);
});

it('does not advertise a failed compiler artifact as a successful PDF', () => {
  render(ui({ build: { state: 'failed', artifacts: [{ role: 'pdf' }] } }));
  expect(screen.getByRole('status')).toHaveTextContent('Не собрано');
  expect(screen.queryByRole('button')).not.toBeInTheDocument();
});

it('names an already opened preview Refresh PDF without implying another build', () => {
  const open = jest.fn();
  render(ui({ build: { state: 'preview_ready', artifacts: [{ role: 'pdf' }] }, previewUrl: 'blob:owned-pdf' }, open));
  expect(screen.queryByRole('button', { name: 'Открыть PDF' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Обновить PDF' }));
  expect(open).toHaveBeenCalledTimes(1);
});

it('does not pretend to refresh an older preview before the current build has an artifact', () => {
  render(ui({ build: { state: 'building', artifacts: [] }, previewUrl: 'blob:previous-pdf' }));
  expect(screen.getByRole('status')).toHaveTextContent('Собираю PDF');
  expect(screen.getByRole('button', { name: 'Обновить PDF' })).toBeDisabled();
});

it('invites opening only a fresh, unopened artifact and withdraws the cue while busy', () => {
  const current = { build: { state: 'preview_ready', source_digest: 'current', artifacts: [{ role: 'pdf' }] },
    project: { source_digest: 'current' } };
  const renderButton = (document, available = true) => <ChakraProvider>
    <PdfPreviewButton document={document} hintAvailable={available} onOpenPdf={jest.fn()} />
  </ChakraProvider>;
  const view = render(renderButton(current));
  expect(screen.getByRole('button', { name: 'Открыть PDF' })).toHaveAttribute('data-action-hint', 'idle');
  for (const [document, available] of [
    [{ ...current, previewBusy: true }, true],
    [{ ...current, project: { source_digest: 'changed' } }, true],
    [{ ...current, project: {} }, true],
    [current, false],
    [{ ...current, previewUrl: 'blob:owned' }, true],
  ]) {
    view.rerender(renderButton(document, available));
    expect(screen.getByRole('button')).not.toHaveAttribute('data-action-hint');
  }
});
