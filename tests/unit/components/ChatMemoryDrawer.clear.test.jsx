import React from 'react';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import ChatMemoryDrawer from '../../../src/features/chat/components/drawers/ChatMemoryDrawer';

/**
 * Полная очистка памяти. Удалять факты по одному было можно, а стереть всё — нет:
 * при десятках записей это занятие, а не операция.
 *
 * 🔴 Действие НЕОБРАТИМО и стирает две разные вещи (список фактов + семантическую память
 * MemOS, которой в списке не видно). Поэтому проверяем не «кнопка есть», а что она
 * спрашивает перед тем как стереть, и что в вопросе названо, чего именно лишится человек.
 */
const FACTS = [
  { id: 'f1', fact_type: 'identity', fact_key: 'Язык', fact_value: 'Python' },
  { id: 'f2', fact_type: 'preference', fact_key: 'Стиль', fact_value: 'Кратко' },
];

const DASHBOARD = {
  text_mem: [{ cube_id: 'c1', memories: [{ memory: 'обсуждали рефакторинг' }, { memory: 'искал жильё' }] }],
};

const renderDrawer = (props = {}) =>
  render(
    <ChakraProvider>
      <ChatMemoryDrawer
        isOpen
        onClose={() => {}}
        memoryFacts={FACTS}
        memoryDashboard={DASHBOARD}
        {...props}
      />
    </ChakraProvider>
  );

describe('ChatMemoryDrawer — очистка памяти', () => {
  it('🔴 первый клик СПРАШИВАЕТ, а не стирает', () => {
    const onClearAll = jest.fn();
    renderDrawer({ onClearAll });

    fireEvent.click(screen.getByText('Очистить всю память'));

    expect(onClearAll).not.toHaveBeenCalled();
    expect(screen.getByText(/Очистить всю долговременную память\?/)).toBeInTheDocument();
  });

  it('стирает только после подтверждения', async () => {
    const onClearAll = jest.fn().mockResolvedValue(undefined);
    renderDrawer({ onClearAll });

    fireEvent.click(screen.getByText('Очистить всю память'));
    // ⚠️ Подтверждение асинхронное (ждёт ответ бэкенда и снимает флаг занятости),
    // поэтому клик — внутри `act`: иначе состояние доедет уже после конца теста.
    await act(async () => {
      fireEvent.click(screen.getByText('Очистить'));
    });

    expect(onClearAll).toHaveBeenCalledTimes(1);
  });

  it('🔴 в подтверждении названы ОБЕ половины памяти с их объёмом', () => {
    // Семантическая память не видна списком: без упоминания человек не узнает, что
    // теряет её тоже, — и «очистить» окажется не тем, на что он соглашался.
    renderDrawer({ onClearAll: jest.fn() });
    fireEvent.click(screen.getByText('Очистить всю память'));

    const dialog = screen.getByRole('alertdialog');
    expect(dialog.textContent).toContain('2 факта');
    expect(dialog.textContent).toContain('2 записи семантической памяти MemOS');
  });

  it('🔴 длинный список свёрнут, иначе кнопка уезжает за экран', () => {
    // Ради неё сворачивание и делалось: при десятках фактов панель тянулась на
    // несколько экранов, и всё, что стоит под списком, было не достать.
    const many = Array.from({ length: 20 }, (_, i) => ({
      id: `m${i}`,
      fact_type: 'context',
      fact_key: `Ключ ${i}`,
      fact_value: `Значение ${i}`,
    }));
    renderDrawer({ onClearAll: jest.fn(), memoryFacts: many });

    expect(screen.getByText('Ключ 4')).toBeInTheDocument();
    expect(screen.queryByText('Ключ 5')).toBeNull();
    expect(screen.getByText(/ещё 15/)).toBeInTheDocument();
    // Счёт остаётся ПОЛНЫМ: «5 фактов» при двадцати сохранённых — это ложь о памяти.
    expect(screen.getByText('20 фактов сохранено')).toBeInTheDocument();
  });

  it('раскрывается по клику', () => {
    const many = Array.from({ length: 20 }, (_, i) => ({
      id: `m${i}`,
      fact_type: 'context',
      fact_key: `Ключ ${i}`,
      fact_value: `Значение ${i}`,
    }));
    renderDrawer({ onClearAll: jest.fn(), memoryFacts: many });

    fireEvent.click(screen.getByText(/ещё 15/));

    expect(screen.getByText('Ключ 19')).toBeInTheDocument();
  });

  it('🔴 выдача поиска не урезается', () => {
    // Урезать результаты по запросу значит спрятать ровно то, что человек искал.
    const many = Array.from({ length: 20 }, (_, i) => ({
      id: `m${i}`,
      fact_type: 'context',
      fact_key: `Ключ ${i}`,
      fact_value: `Значение ${i}`,
    }));
    renderDrawer({ onClearAll: jest.fn(), memoryFacts: many, onSearch: jest.fn() });

    fireEvent.change(screen.getByLabelText('Поиск по памяти'), { target: { value: 'ключ' } });

    expect(screen.getByText('Ключ 19')).toBeInTheDocument();
    expect(screen.queryByText(/ещё/)).toBeNull();
  });

  it('короткий список не сворачивается', () => {
    renderDrawer({ onClearAll: jest.fn() });

    // ⚠️ Ищем «ещё» БЕЗ цифры следом: с `/ещё \d/` страж был слепым — при сворачивании
    // двух фактов подпись выходила «…ещё -3», минус ломал совпадение, и тест проходил
    // ровно в том случае, который должен был поймать.
    expect(screen.queryByText(/ещё/)).toBeNull();
    expect(screen.getByText('Стиль')).toBeInTheDocument();
  });

  it('кнопки нет, когда стирать нечего', () => {
    renderDrawer({ onClearAll: jest.fn(), memoryFacts: [], memoryDashboard: null });

    expect(screen.queryByText('Очистить всю память')).toBeNull();
  });

  it('память в MemOS есть, а фактов нет — кнопка всё равно нужна', () => {
    // Иначе очистить семантическую память было бы невозможно в принципе: она
    // наполняется сама и в списке фактов не показывается.
    renderDrawer({ onClearAll: jest.fn(), memoryFacts: [] });

    expect(screen.getByText('Очистить всю память')).toBeInTheDocument();
  });
});
