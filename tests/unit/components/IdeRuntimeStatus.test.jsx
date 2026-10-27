import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import IdeRuntimeStatus from '@features/workspace-room/components/IdeRuntimeStatus';

const view = (state) => <ChakraProvider><IdeRuntimeStatus runtime={{ state }} /></ChakraProvider>;

it('keeps details unmounted until opened and restores keyboard focus after Escape', async () => {
  render(view('ready'));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  const trigger = screen.getByRole('button', { name: 'Состояние среды: Среда доступна' });
  fireEvent.click(trigger);
  const close = await screen.findByRole('button', { name: 'Закрыть сведения о среде' });
  await waitFor(() => expect(close).toHaveFocus());
  fireEvent.keyDown(close, { key: 'Escape' });
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  await waitFor(() => expect(trigger).toHaveFocus());
});

it('updates the passive details without suggesting replacement of an expired project', async () => {
  const rendered = render(view('ready'));
  fireEvent.click(screen.getByRole('button', { name: 'Состояние среды: Среда доступна' }));
  await screen.findByRole('dialog');
  rendered.rerender(view('expired'));
  expect(screen.getByRole('dialog')).toHaveTextContent('Новая пустая среда автоматически не создаётся');
  expect(screen.queryByRole('button', { name: /Создать|Запустить/ })).not.toBeInTheDocument();
});
