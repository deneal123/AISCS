import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import theme from '../../../src/theme';
import ComposerVoiceControl from '../../../src/features/chat/components/composer/ComposerVoiceControl';
import ComposerVoicePreview from '../../../src/features/chat/components/composer/ComposerVoicePreview';

const wrapper = ({ children }) => <ChakraProvider theme={theme}>{children}</ChakraProvider>;

it.each([
  [{}, 'button', 'Голосовой ввод'],
  [{ recordingState: 'recording', elapsedSec: 72 }, 'button', 'Остановить запись'],
  [{ isTranscribing: true }, 'status', 'Распознаю голос…'],
  [{ recordingState: 'requesting' }, 'status', 'Ожидаю разрешения микрофона…'],
])('keeps a fixed touch target in every voice state: %j', (props, role, name) => {
  render(<ComposerVoiceControl {...props} />, { wrapper });
  const control = screen.getByRole(role, { name });
  expect(control).toHaveStyle({ width: '44px', height: '44px' });
  expect(control.querySelector('[data-composer-action-surface]')).toHaveStyle({ width: '32px', height: '32px' });
});

it('keeps the elapsed time visible and stops only on explicit activation', () => {
  const toggle = jest.fn();
  render(<ComposerVoiceControl recordingState="recording" elapsedSec={72} onToggle={toggle} />, { wrapper });
  expect(screen.getByText('1:12')).toBeVisible();
  expect(screen.getByRole('timer')).toHaveTextContent('1:12');
  expect(screen.getByRole('button', { name: 'Остановить запись' })).toHaveAccessibleDescription('1:12');
  expect(toggle).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Остановить запись' }));
  expect(toggle).toHaveBeenCalledTimes(1);
});

it('announces transcription without presenting a second actionable microphone', () => {
  render(<ComposerVoiceControl isTranscribing />, { wrapper });
  expect(screen.getByRole('status', { name: 'Распознаю голос…' })).toBeInTheDocument();
  expect(screen.queryByRole('button')).not.toBeInTheDocument();
});

it('keeps voice preview actions touch-sized and preserves explicit edit/discard ownership', () => {
  const edit = jest.fn();
  const discard = jest.fn();
  render(<ComposerVoicePreview text="Сохранённый голос" onEdit={edit} onDiscard={discard} />, { wrapper });
  const editButton = screen.getByRole('button', { name: 'Дописать в поле ввода' });
  const discardButton = screen.getByRole('button', { name: 'Убрать голосовое' });
  expect(editButton).toHaveStyle({ width: '44px', height: '44px' });
  expect(discardButton).toHaveStyle({ width: '44px', height: '44px' });
  fireEvent.click(editButton);
  expect(edit).toHaveBeenCalledTimes(1);
  expect(discard).not.toHaveBeenCalled();
  fireEvent.click(discardButton);
  expect(discard).toHaveBeenCalledTimes(1);
});
