import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import { DocumentChecksBar } from '@features/workspace-room/components/DocumentChecksBar';

it('keeps checks compact and does not manufacture completed stages before a build', () => {
  const onToggle = jest.fn();
  render(<ChakraProvider><DocumentChecksBar document={{}} expanded={false} onToggle={onToggle} /></ChakraProvider>);
  const summary = screen.getByLabelText('Краткий статус PDF');
  expect(summary).toHaveTextContent('Техническая: не запускалась');
  expect(summary).toHaveTextContent('Визуальная: не запускалась');
  expect(summary).toHaveTextContent('Библиотека: не сохранено');
  expect(screen.queryByLabelText('Этапы подготовки документа')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Проверки' }));
  expect(onToggle).toHaveBeenCalledTimes(1);
});

it.each([
  ['preview_ready', undefined, 'пройдена', 'не запускалась', 'не сохранено'],
  ['visual_pending', 'pending_audit', 'пройдена', 'проверка требуется', 'Ожидает визуальной проверки'],
  ['ready', 'pending_delivery', 'пройдена', 'пройдена', 'Ожидает сохранения в Библиотеку'],
  ['ready', 'delivered', 'пройдена', 'пройдена', 'сохранено'],
  ['failed', undefined, 'состояние уточняется', 'не запускалась', 'не сохранено'],
])('keeps real audit and delivery states for %s/%s', (state, publication_state, technical, visual, library) => {
  render(<ChakraProvider><DocumentChecksBar document={{ build: { state, publication_state } }} expanded={false} /></ChakraProvider>);
  const summary = screen.getByLabelText('Краткий статус PDF');
  expect(summary).toHaveTextContent(`Техническая: ${technical}`);
  expect(summary).toHaveTextContent(`Визуальная: ${visual}`);
  expect(summary).toHaveTextContent(`Библиотека: ${library}`);
});
