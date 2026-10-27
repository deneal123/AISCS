import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import ChatEmptyState from '@features/chat/components/ChatEmptyState';

const personas = ['Инженер', 'Аналитик', 'Учёный'].map((label, id) => ({ id: String(id), label, hint: 'Описание' }));
it('убирает вводный текст и сохраняет названия и порядок выбора у иконок', () => {
  render(<ChakraProvider><ChatEmptyState personas={personas} personaIds={['1', '0']} /></ChakraProvider>);
  expect(screen.queryByText(/Выберите специализацию/)).not.toBeInTheDocument();
  const engineer = screen.getByRole('button', { name: 'Инженер' });
  expect(engineer).toHaveAttribute('aria-pressed', 'true');
  expect(engineer).toHaveAttribute('title', 'Инженер — Описание');
  expect(engineer.querySelector('[aria-hidden="true"]')).toBeInTheDocument();
  expect(engineer).toHaveTextContent('2');
  expect(screen.getByRole('button', { name: 'Аналитик' })).toHaveTextContent('1');
});

it('сохраняет приглашение ввести задачу при пустом реестре личностей', () => {
  render(<ChakraProvider><ChatEmptyState /></ChakraProvider>);
  expect(screen.getByText('Опишите задачу — или приложите файл.')).toBeVisible();
});
it('renders interactive specializations immediately, preserving the two-persona cap', () => {
  const change = jest.fn();
  render(<ChakraProvider><ChatEmptyState personas={personas} personaIds={['0', '1']} onPersonaIdsChange={change} /></ChakraProvider>);
  const engineer = screen.getByRole('button', { name: /Инженер/ });
  expect(engineer).toBeVisible();
  expect(engineer.closest('.in-view-reveal')).toBeNull();
  expect(screen.getByRole('button', { name: /Учёный/ })).toBeDisabled();
  expect(engineer).not.toHaveAttribute('data-action-hint');
  expect(screen.getByRole('button', { name: /Учёный/ })).not.toHaveAttribute('data-action-hint');
  fireEvent.click(engineer);
  expect(change).toHaveBeenCalledWith(['1']);
});

it('offers exploration only for personalities not yet selected', () => {
  render(<ChakraProvider><ChatEmptyState personas={personas} personaIds={['0']} /></ChakraProvider>);
  expect(screen.getByRole('button', { name: /Инженер/ })).not.toHaveAttribute('data-action-hint');
  expect(screen.getByRole('button', { name: /Аналитик/ })).toHaveAttribute('data-action-hint', 'hover');
});
