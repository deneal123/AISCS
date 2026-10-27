import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import MemosSection from '../../../src/features/chat/components/drawers/MemosSection';
import { extractMemosMemories, memoryDisplayText } from '../../../src/features/chat/components/drawers/memoryPresentation';

const dashboard = items => ({ text_mem: [{ memories: items }] });
function show(items) {
  render(<ChakraProvider><MemosSection dashboard={dashboard(items)} /></ChakraProvider>);
}

it.each([1, 2, 7])('действительно скрывает и раскрывает содержимое при %s записях', count => {
  show(Array.from({ length: count }, (_, n) => `Воспоминание ${n}`));
  fireEvent.click(screen.getByRole('button', { name: 'Скрыть семантическую память' }));
  expect(screen.queryByText(`Воспоминание ${count - 1}`)).not.toBeInTheDocument();
  const expand = screen.getByRole('button', { name: 'Раскрыть семантическую память' });
  expect(expand).toHaveAttribute('aria-expanded', 'false');
  fireEvent.click(expand);
  expect(screen.getByText(`Воспоминание ${count - 1}`)).toBeVisible();
});

it('сворачивает длинный текст отдельно от всей секции', () => {
  const text = 'Длинное воспоминание. '.repeat(80);
  show([text]);
  fireEvent.click(screen.getByRole('button', { name: 'Читать запись' }));
  expect(screen.getByRole('region', { name: 'Полный текст записи 1' })).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Свернуть запись' }));
  expect(screen.queryByRole('region', { name: 'Полный текст записи 1' })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Скрыть семантическую память' })).toHaveAttribute('aria-expanded', 'true');
});

it('листит записи по пять без раскрытия огромного списка', () => {
  show(Array.from({ length: 12 }, (_, n) => `Текст ${n}`));
  expect(screen.getByText('Текст 11')).toBeVisible();
  expect(screen.queryByText('Текст 6')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Следующая страница' }));
  expect(screen.getByText('Текст 6')).toBeVisible();
  expect(screen.queryByText('Текст 11')).not.toBeInTheDocument();
});

it('представляет корректную JSON-историю как диалог, не теряя текст', () => {
  const source = 'Резюме: {"role":"user","content":"Привет\\nМир","ts":123}, {"role":"assistant","content":"Ответ"}';
  expect(memoryDisplayText(source)).toBe('Резюме:\n\nВы: Привет\nМир\n\nАссистент: Ответ');
  const unknown = '{"role":"tool","content":"Нельзя терять"}';
  expect(memoryDisplayText(unknown)).toBe(unknown);
  expect(memoryDisplayText('обычный текст')).toBe('обычный текст');
  expect(memoryDisplayText('{"role":broken')).toBe('{"role":broken');
  expect(extractMemosMemories({ text_mem: [{ memories: [null, {}, { content: { private: true } }, 'Текст'] }] })).toEqual(['Текст']);
});
