import { fireEvent, render, screen } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import theme from '../../../src/theme';
import IdeProjectRecovery from '../../../src/features/workspace-room/components/IdeProjectRecovery';

const show = overrides => {
  const saved = { available: true, history: { items: [] }, show: jest.fn(), load: jest.fn(), ...overrides };
  const onNew = jest.fn();
  render(<ChakraProvider theme={theme}><IdeProjectRecovery saved={saved} onNew={onNew} /></ChakraProvider>);
  return { saved, onNew };
};

it('routes an expired project to its existing history owner without restoring automatically', () => {
  const { saved, onNew } = show({ history: { items: [{ state: 'published' }] } });
  expect(screen.getByRole('heading', { name: 'Среда завершена' })).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Открыть историю' }));
  expect(saved.show).toHaveBeenCalledTimes(1);
  expect(onNew).not.toHaveBeenCalled();
});

it('does not declare history empty while it is loading', () => {
  show({ loading: true, history: null });
  expect(screen.getByText('Проверяю сохранённые версии…')).toBeVisible();
  expect(screen.queryByRole('button', { name: 'Новый проект' })).not.toBeInTheDocument();
});

it('сохраняет фокусируемую кнопку открытия при фоновом обновлении известной истории', () => {
  const saved = { available: true, history: { items: [{ state: 'published' }] }, show: jest.fn() };
  const view = state => <ChakraProvider theme={theme}><IdeProjectRecovery saved={state} /></ChakraProvider>;
  const { rerender } = render(view(saved));
  const opener = screen.getByRole('button', { name: 'Открыть историю', exact: true });
  rerender(view({ ...saved, loading: true }));
  expect(screen.getByRole('button', { name: 'Открыть историю', exact: true })).toBe(opener);
  expect(opener).toBeEnabled();
  expect(opener).toHaveAttribute('aria-busy', 'true');
  opener.focus();
  expect(opener).toHaveFocus();
  fireEvent.click(opener);
  expect(saved.show).toHaveBeenCalledTimes(1);
  rerender(view(saved));
  expect(screen.getByRole('button', { name: 'Открыть историю', exact: true })).toBe(opener);
  expect(opener).toHaveFocus();
});

it('retries a failed read instead of offering an empty replacement', () => {
  const { saved, onNew } = show({ error: 'read failed', history: null });
  fireEvent.click(screen.getByRole('button', { name: 'Повторить проверку' }));
  expect(saved.load).toHaveBeenCalledTimes(1);
  expect(onNew).not.toHaveBeenCalled();
  expect(screen.queryByText(/Сохранённых версий нет/)).not.toBeInTheDocument();
});

it.each([{ intent: { kind: 'save' } }, { history: { items: [{ state: 'pending' }] } },
  { history: { items: [], last_restore: { state: 'pending' } } }])('keeps unresolved work reachable through history: %o', state => {
  const { saved } = show(state);
  expect(screen.getByText(/Проверьте результат предыдущего сохранения/)).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Открыть историю' }));
  expect(saved.show).toHaveBeenCalledTimes(1);
});

it('does not duplicate the toolbar new-project action when history is empty', () => {
  const { onNew } = show();
  expect(screen.getByText(/Сохранённых версий нет/)).toBeVisible();
  expect(onNew).not.toHaveBeenCalled();
  expect(screen.queryByRole('button', { name: 'Новый проект' })).not.toBeInTheDocument();
  expect(screen.queryByText(/Можно начать отдельный/)).not.toBeInTheDocument();
});

it('does not equate an unavailable feature with an empty history', () => {
  show({ available: false, history: null });
  expect(screen.getByText(/История сохранённых версий сейчас недоступна/)).toBeVisible();
  expect(screen.queryByText(/Сохранённых версий нет/)).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Новый проект' })).not.toBeInTheDocument();
});
