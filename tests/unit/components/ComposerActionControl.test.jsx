import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import { FiPaperclip } from '../../../src/shared/icons';
import theme from '../../../src/theme';
import ComposerActionControl from '../../../src/features/chat/components/composer/ComposerActionControl';
import ChatComposerPanel from '../../../src/features/chat/components/composer/ChatComposerPanel';

const wrapper = ({ children }) => <ChakraProvider theme={theme}>{children}</ChakraProvider>;

it.each([{}, { isLoading: true }, { isDisabled: true }])('сохраняет компактную скрепку во всех состояниях: %j', (props) => {
  const click = jest.fn();
  render(<ComposerActionControl aria-label="Прикрепить файл" icon={FiPaperclip} onClick={click} {...props} />, { wrapper });
  const button = screen.getByRole('button', { name: 'Прикрепить файл' });
  expect(button).toHaveStyle({ width: '44px', height: '44px' });
  expect(button.querySelector('[data-composer-action-surface]')).toHaveStyle({ width: '32px', height: '32px' });
  fireEvent.click(button);
  expect(click).toHaveBeenCalledTimes(props.isDisabled || props.isLoading ? 0 : 1);
  if (props.isLoading) expect(button).toHaveAttribute('aria-busy', 'true');
  else expect(button.querySelector('svg')).toHaveStyle({ width: '16px', height: '16px' });
});

it('открывает прежний выбор файла и не повторяет его во время загрузки', () => {
  const fileInputRef = React.createRef();
  const view = render(<ChatComposerPanel fileInputRef={fileInputRef} isAuthenticated />, { wrapper });
  const select = jest.spyOn(fileInputRef.current, 'click').mockImplementation(() => {});
  const attachment = screen.getByRole('button', { name: 'Прикрепить файл' });
  const microphone = screen.getByRole('button', { name: 'Голосовой ввод' });
  for (const button of [attachment, microphone]) {
    expect(button.querySelector('[data-composer-action-surface]')).toHaveStyle({ width: '32px', height: '32px' });
    expect(button.querySelector('svg')).toHaveStyle({ width: '16px', height: '16px' });
  }
  fireEvent.click(attachment);
  expect(select).toHaveBeenCalledTimes(1);
  view.rerender(<ChatComposerPanel fileInputRef={fileInputRef} isAuthenticated isFileUploading />);
  expect(screen.getByRole('button', { name: 'Прикрепить файл' })).toBe(attachment);
  fireEvent.click(attachment);
  expect(select).toHaveBeenCalledTimes(1);
  select.mockRestore();
});
