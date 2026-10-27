import { fireEvent, render, screen } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import theme from '../../../src/theme';
import IdeProjectStart from '@features/workspace-room/components/IdeProjectStart';

const show = (overrides = {}, hasThread = true) => {
  const setup = { create: jest.fn(), ...overrides };
  render(<ChakraProvider theme={theme}><IdeProjectStart setup={setup} hasThread={hasThread} /></ChakraProvider>);
  return setup;
};

it('focuses the name and describes an additional project without a false empty-chat claim', () => {
  show();
  expect(screen.getByRole('textbox', { name: 'Название проекта' })).toHaveFocus();
  expect(screen.getByText(/Текущий проект не изменится/)).toBeVisible();
  expect(screen.queryByText(/пока нет репозиториев/)).not.toBeInTheDocument();
  expect(screen.queryByText(/запустите его отдельную среду/)).not.toBeInTheDocument();
});

it('validates an empty name in the form and returns focus without dispatch', () => {
  const setup = show();
  fireEvent.click(screen.getByRole('button', { name: 'Создать проект' }));
  expect(setup.create).not.toHaveBeenCalled();
  expect(screen.getByRole('textbox')).toHaveAttribute('aria-invalid', 'true');
  expect(screen.getByRole('textbox')).toHaveFocus();
});

it('keeps the immutable name available for an explicit retry after uncertain creation', () => {
  const setup = show({ submittedName: 'A', locked: true, error: 'create' });
  expect(screen.getByRole('textbox')).toHaveValue('A');
  expect(screen.getByRole('textbox')).toHaveAttribute('readonly');
  expect(screen.getByRole('alert')).toHaveTextContent('Повтор использует тот же запрос');
  fireEvent.click(screen.getByRole('button', { name: 'Повторить создание' }));
  expect(setup.create).toHaveBeenCalledWith('A');
});

it('does not submit again while creation is busy', () => {
  const setup = show({ submittedName: 'A', locked: true, busy: 'create' });
  fireEvent.click(screen.getByRole('button', { name: 'Создать проект' }));
  expect(setup.create).not.toHaveBeenCalled();
  expect(screen.getByRole('textbox')).toHaveAttribute('readonly');
});

it('does not expose a create form without a thread', () => {
  show({}, false);
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Создать проект' })).not.toBeInTheDocument();
});
