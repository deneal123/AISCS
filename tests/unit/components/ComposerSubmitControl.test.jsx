import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import theme from '../../../src/theme';
import ComposerSubmitControl from '../../../src/features/chat/components/composer/ComposerSubmitControl';

const wrapper = ({ children }) => <ChakraProvider theme={theme}>{children}</ChakraProvider>;

it.each([
  [{}, 'Отправить', true],
  [{ canSend: true }, 'Отправить', false],
  [{ uploading: true }, 'Отправить', true],
  [{ streaming: true }, 'Остановить генерацию', false],
])('keeps a smaller visible surface inside a full touch target: %j', (props, name, disabled) => {
  render(<ComposerSubmitControl {...props} />, { wrapper });
  const button = screen.getByRole('button', { name, exact: true });
  // Browser coverage resolves Chakra's shadow CSS variables; jsdom does not.
  expect(button).toHaveStyle({ width: '44px', height: '44px' });
  expect(button.querySelector('[data-composer-submit-surface]')).toHaveStyle({ width: '32px', height: '32px' });
  if (disabled) expect(button).toBeDisabled();
  else expect(button).toBeEnabled();
});

it('preserves disabled, send and Stop handlers when the presentation switches', () => {
  const send = jest.fn();
  const stop = jest.fn();
  const view = render(<ComposerSubmitControl onSend={send} onStop={stop} />, { wrapper });
  fireEvent.click(screen.getByRole('button', { name: 'Отправить', exact: true }));
  expect(send).not.toHaveBeenCalled();
  view.rerender(<ComposerSubmitControl canSend onSend={send} onStop={stop} />);
  fireEvent.click(screen.getByRole('button', { name: 'Отправить', exact: true }));
  expect(send).toHaveBeenCalledTimes(1);
  view.rerender(<ComposerSubmitControl streaming onSend={send} onStop={stop} />);
  fireEvent.click(screen.getByRole('button', { name: 'Остановить генерацию', exact: true }));
  expect(stop).toHaveBeenCalledTimes(1);
  expect(send).toHaveBeenCalledTimes(1);
});
