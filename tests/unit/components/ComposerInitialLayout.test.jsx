import React from 'react';
import { act, render, screen } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import theme from '../../../src/theme';
import ChatComposerPanel from '../../../src/features/chat/components/composer/ChatComposerPanel';

it.each([false, true])('starts with one native text row (workbench: %s)', (workbenchMode) => {
  render(<ChakraProvider theme={theme}><ChatComposerPanel
    fileInputRef={React.createRef()} isAuthenticated workbenchMode={workbenchMode} /></ChakraProvider>);
  const input = screen.getByRole('textbox', { name: 'Сообщение', exact: true });
  expect(input).toHaveAttribute('rows', '1');
  expect(input).toHaveStyle({ height: '56px' });
});

it('uses the destination width synchronously, without waiting for an observer frame', () => {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1440 });
  let width = 480;
  const rects = jest.spyOn(HTMLElement.prototype, 'getClientRects').mockImplementation(function () {
    return this.hasAttribute('data-composer-container') ? [{}] : [];
  });
  const size = jest.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockImplementation(() => width);
  const ref = React.createRef();
  let view;
  try {
    view = render(<ChakraProvider theme={theme}><ChatComposerPanel ref={ref}
      fileInputRef={React.createRef()} isAuthenticated /></ChakraProvider>);
    const button = screen.getByRole('button', { name: 'Режим: Авто', exact: true });
    expect(button.textContent).toBe('');
    act(() => { width = 1000; ref.current.refreshLayout(); });
    expect(button).toHaveTextContent('Режим: Авто');
    act(() => { width = 480; ref.current.refreshLayout(); });
    expect(button.textContent).toBe('');
  } finally {
    view?.unmount(); rects.mockRestore(); size.mockRestore();
  }
});
