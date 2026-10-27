import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import PersistentChatSurface from '@features/chat/components/PersistentChatSurface';

jest.mock('@features/chat/components/ChatMessagesArea', () => ({ documentMode }) => <div>{documentMode ? 'История документа' : 'История чата'}</div>);
jest.mock('@features/chat/components/composer/ChatComposerPanel', () => {
  const React = require('react');
  return React.forwardRef(function ComposerMock(props, ref) {
    const input = React.useRef();
    React.useImperativeHandle(ref, () => ({ refreshLayout: () => props.onMeasure?.(input.current.parentElement.closest('[data-slot]')?.dataset.slot) }));
    return <textarea ref={input} aria-label="Черновик" data-hint-paused={props.hintPaused} />;
  });
});

it('does not invite a new input while the anchored run awaits a decision', () => {
  const slot = document.createElement('div');
  document.body.append(slot);
  const session = { anchorMessageId: 'user-1', status: 'awaiting_confirmation', events: [{ offer: {
    offer_id: 'offer-1', status: 'pending', offered_at: new Date().toISOString(), expires_in_sec: 300,
  } }] };
  const chat = { messages: { visibleMessages: [{ id: 'user-1', type: 'user' }], activeTraceSession: session }, composer: {} };
  const view = render(<PersistentChatSurface target={slot} chat={chat} />);
  expect(screen.getByLabelText('Черновик')).toHaveAttribute('data-hint-paused', 'true');
  view.rerender(<PersistentChatSurface target={slot} chat={{ ...chat, messages: {
    ...chat.messages, activeTraceSession: { ...session, status: 'done' },
  } }} />);
  expect(screen.getByLabelText('Черновик')).toHaveAttribute('data-hint-paused', 'false');
  view.unmount(); slot.remove();
});

it('moves the same uncontrolled composer node between Chat and PDF without losing draft', () => {
  const chatSlot = document.createElement('div');
  const pdfSlot = document.createElement('div');
  document.body.append(chatSlot, pdfSlot);
  chatSlot.dataset.slot = 'chat'; pdfSlot.dataset.slot = 'pdf';
  const onMeasure = jest.fn();
  const chat = { messages: {}, composer: { onMeasure }, composerRef: React.createRef() };
  const view = render(<PersistentChatSurface target={chatSlot} chat={chat} />);
  const input = screen.getByLabelText('Черновик');
  expect(screen.getByText('История чата')).toBeInTheDocument();
  expect(onMeasure).toHaveBeenLastCalledWith('chat');
  fireEvent.input(input, { target: { value: 'Не терять текст' } });
  view.rerender(<PersistentChatSurface target={pdfSlot} chat={chat} documentMode />);
  expect(pdfSlot.contains(input)).toBe(true);
  expect(onMeasure).toHaveBeenLastCalledWith('pdf');
  expect(screen.queryByText('История документа')).not.toBeInTheDocument();
  expect(screen.getByLabelText('Черновик')).toBe(input);
  expect(input).toHaveValue('Не терять текст');
  view.rerender(<PersistentChatSurface target={chatSlot} chat={chat} />);
  expect(chatSlot.contains(input)).toBe(true);
  expect(screen.getByText('История чата')).toBeInTheDocument();
  expect(input).toHaveValue('Не терять текст');
  view.rerender(<PersistentChatSurface target={pdfSlot} chat={chat} ideMode />);
  expect(pdfSlot.contains(input)).toBe(true);
  expect(screen.queryByText('История чата')).not.toBeInTheDocument();
  expect(input).toHaveValue('Не терять текст');
  expect(screen.getByText('Что сделаем?')).toBeVisible();
  view.unmount(); chatSlot.remove(); pdfSlot.remove();
});

it('передаёт состояние dock от владельца ассистента без чтения DOM портала', () => {
  const slot = document.createElement('div');
  document.body.append(slot);
  const onDockExpandedChange = jest.fn();
  const props = { target: slot, chat: { messages: {}, composer: {} }, onDockExpandedChange };
  const view = render(<PersistentChatSurface {...props} documentMode />);
  expect(onDockExpandedChange).toHaveBeenLastCalledWith(false);
  view.rerender(<PersistentChatSurface {...props} documentMode
    chat={{ ...props.chat, messages: { isLoading: true } }} />);
  expect(onDockExpandedChange).toHaveBeenLastCalledWith(true);
  view.rerender(<PersistentChatSurface {...props} />);
  expect(onDockExpandedChange).toHaveBeenLastCalledWith(false);
  view.unmount(); slot.remove();
});
