import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import theme from '../../../src/theme';
import IdeMoveFileButton from '@features/workspace-room/components/IdeMoveFileButton';

test('keeps its accessible action and supplies a focus description without moving a file', async () => {
  const onClick = jest.fn();
  render(<ChakraProvider theme={theme}><IdeMoveFileButton onClick={onClick} /></ChakraProvider>);
  const action = screen.getByRole('button', { name: 'Переместить', exact: true });
  fireEvent.focus(action);
  await waitFor(() => expect(screen.getByRole('tooltip')).toHaveTextContent('Переместить файл'));
  expect(onClick).not.toHaveBeenCalled();
  fireEvent.click(action);
  expect(onClick).toHaveBeenCalledTimes(1);
});

test('does not dispatch a move while disabled', () => {
  const onClick = jest.fn();
  render(<ChakraProvider theme={theme}><IdeMoveFileButton onClick={onClick} isDisabled /></ChakraProvider>);
  const action = screen.getByRole('button', { name: 'Переместить', exact: true });
  expect(action).toBeDisabled();
  fireEvent.click(action);
  expect(onClick).not.toHaveBeenCalled();
});
