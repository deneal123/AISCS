import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import IdeAgentPane from '@features/workspace-room/components/IdeAgentPane';

it('keeps passive details unmounted and shares the runtime help initial/return focus contract', async () => {
  render(<ChakraProvider><IdeAgentPane name="Проект" /></ChakraProvider>);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  const trigger = screen.getByRole('button', { name: 'Об агенте IDE', exact: true });
  fireEvent.click(trigger);
  const close = await screen.findByRole('button', { name: 'Закрыть сведения об агенте' });
  await waitFor(() => expect(close).toHaveFocus());
  expect(screen.getByRole('dialog')).toHaveTextContent('Проект');
  fireEvent.keyDown(close, { key: 'Escape' });
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  await waitFor(() => expect(trigger).toHaveFocus());
  fireEvent.click(trigger);
  await waitFor(() => expect(screen.getByRole('dialog')).toBeVisible());
  expect(screen.getByRole('dialog')).toHaveStyle({ visibility: 'visible', opacity: 1, transform: 'none' });
});

it('keeps the credit disclosure visible without repeating the whole explanation in idle chrome', () => {
  render(<ChakraProvider><IdeAgentPane name="Проект" statusHint="Среда завершена." /></ChakraProvider>);
  expect(screen.getByText('Запросы за кредиты')).toBeVisible();
  expect(screen.getByRole('status')).toHaveTextContent('Среда завершена.');
  expect(screen.queryByText(/Агент читает и меняет файлы/)).not.toBeInTheDocument();
});
