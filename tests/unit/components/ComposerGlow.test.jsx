import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import theme from '../../../src/theme';
import ChatComposerPanel from '../../../src/features/chat/components/composer/ChatComposerPanel';
import ChatHeaderBar from '../../../src/features/chat/components/ChatHeaderBar';

jest.mock('../../../src/features/billing', () => ({
  CreditsPill: () => null,
  useBillingContext: () => ({ balance: null }),
}));
jest.mock('../../../src/features/chat/components/ProviderAvailability', () => () => null);

const wrapper = ({ children }) => <ChakraProvider theme={theme}>{children}</ChakraProvider>;
const shell = () => document.querySelector('[data-composer-input-surface]');
const base = { fileInputRef: React.createRef(), isAuthenticated: true };

it('offers an idle invitation only while ready, and restores it after execution', () => {
  const onSubmit = jest.fn();
  const view = render(<ChatComposerPanel {...base} onSubmit={onSubmit} />, { wrapper });
  const input = screen.getByRole('textbox', { name: 'Сообщение' });
  expect(shell()).toHaveAttribute('data-action-hint', 'idle');
  fireEvent.input(input, { target: { value: 'Проверить проект' } });
  fireEvent.click(screen.getByRole('button', { name: 'Отправить', exact: true }));
  expect(onSubmit).toHaveBeenCalledWith('Проверить проект');
  view.rerender(<ChatComposerPanel {...base} disabled isStreaming onSubmit={onSubmit} />);
  expect(shell()).not.toHaveAttribute('data-action-hint');
  view.rerender(<ChatComposerPanel {...base} onSubmit={onSubmit} />);
  expect(shell()).toHaveAttribute('data-action-hint', 'idle');
  expect(input).toHaveValue('Проверить проект');
});

it.each([
  ['running', { isStreaming: true }],
  ['preparing or blocked', { disabled: true }],
  ['uploading', { isFileUploading: true }],
  ['requesting microphone', { isRequestingPermission: true }],
  ['recording', { isRecording: true }],
  ['transcribing', { isVoiceTranscribing: true }],
  ['compacting context', { compacting: true }],
  ['awaiting an explicit decision', { hintPaused: true }],
  ['unavailable model', { selectedModel: 'missing', availableModels: [] }],
  ['hidden workbench composer', { visible: false }],
])('does not advertise input readiness when %s', (_name, props) => {
  render(<ChatComposerPanel {...base} {...props} />, { wrapper });
  expect(shell()).not.toHaveAttribute('data-action-hint');
});

it('removes the input invitation while its choice panel is open', () => {
  render(<ChatComposerPanel {...base} />, { wrapper });
  fireEvent.click(screen.getByRole('button', { name: 'Режим: Авто' }));
  expect(shell()).not.toHaveAttribute('data-action-hint');
});

it('marks the current peer statically and invites only to other destinations', () => {
  const onSurfaceChange = jest.fn();
  const view = render(<ChatHeaderBar surface="chat" onSurfaceChange={onSurfaceChange} />, { wrapper });
  for (const [surface, label] of [['chat', 'Чат'], ['work', 'IDE'], ['pdf', 'PDF']]) {
    view.rerender(<ChatHeaderBar surface={surface} onSurfaceChange={onSurfaceChange} />);
    const selected = screen.getByRole('button', { name: label, exact: true });
    expect(selected).not.toHaveAttribute('data-action-hint');
    expect(selected).toHaveAttribute('aria-pressed', 'true');
    expect(document.querySelectorAll('[data-action-hint="hover"]')).toHaveLength(2);
    fireEvent.click(selected);
    expect(onSurfaceChange).toHaveBeenLastCalledWith(surface);
  }
});
