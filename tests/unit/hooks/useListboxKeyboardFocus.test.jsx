import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { useListboxKeyboardFocus } from '../../../src/shared/hooks/useListboxKeyboardFocus';

function Harness({ enabled = true }) {
  const focus = useListboxKeyboardFocus(enabled);
  return <><button type="button">Outside</button><div {...focus.props}>
    <input aria-label="List input" />
  </div><output aria-label="Keyboard focus">{String(focus.visible)}</output></>;
}

it('does not style programmatic or pointer focus as keyboard navigation', () => {
  render(<Harness />);
  const input = screen.getByRole('textbox');
  act(() => input.focus());
  expect(screen.getByLabelText('Keyboard focus')).toHaveTextContent('false');
  fireEvent.pointerDown(input);
  expect(screen.getByLabelText('Keyboard focus')).toHaveTextContent('false');
});

it('tracks Tab from outside, arrow navigation, pointer takeover and blur', () => {
  render(<Harness />);
  const outside = screen.getByRole('button');
  const input = screen.getByRole('textbox');
  const status = screen.getByLabelText('Keyboard focus');
  act(() => outside.focus());
  fireEvent.keyDown(outside, { key: 'Tab' });
  expect(status).toHaveTextContent('false');
  act(() => input.focus());
  expect(status).toHaveTextContent('true');
  fireEvent.pointerMove(input);
  expect(status).toHaveTextContent('false');
  fireEvent.keyDown(input, { key: 'ArrowDown' });
  expect(status).toHaveTextContent('true');
  act(() => outside.focus());
  expect(status).toHaveTextContent('false');
  fireEvent.keyDown(outside, { key: 'Tab' });
  act(() => input.focus());
  fireEvent.pointerDown(outside);
  expect(status).toHaveTextContent('false');
});

it('does not activate for ordinary selects and removes document listeners', () => {
  const remove = jest.spyOn(document, 'removeEventListener');
  const view = render(<Harness enabled={false} />);
  const input = screen.getByRole('textbox');
  act(() => input.focus());
  fireEvent.keyDown(input, { key: 'ArrowDown' });
  expect(screen.getByLabelText('Keyboard focus')).toHaveTextContent('false');
  view.rerender(<Harness />);
  view.unmount();
  expect(remove).toHaveBeenCalledWith('keydown', expect.any(Function), true);
  expect(remove).toHaveBeenCalledWith('pointerdown', expect.any(Function), true);
  remove.mockRestore();
});
