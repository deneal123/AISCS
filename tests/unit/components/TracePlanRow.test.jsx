import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import TraceEventRow from '../../../src/features/chat/components/trace/TraceEventRow';

/**
 * План решения в трейс-панели.
 *
 * 🔴 Жалоба: человек включил режим «Планирование», план строился, подмешивался в промпт
 * и влиял на ответ — а наружу уезжало ОДНО ЧИСЛО («План готов: 7 шагов»). Узнать, что
 * именно было запланировано, было негде. Тумблер, чьё действие ненаблюдаемо, неотличим
 * от выключенного.
 */
const PLAN = '1. Прочитать резюме\n2. Выделить достижения\n3. Предложить правки';

const renderPlan = (props = {}) =>
  render(
    <ChakraProvider>
      <TraceEventRow
        event={{
          id: 'p1',
          kind: 'plan',
          title: 'План готов: 3 шаг(ов)',
          detail: PLAN,
          agent: 'planner',
          timestamp: '2026-07-26T17:10:00Z',
          ...props,
        }}
      />
    </ChakraProvider>
  );

describe('TraceEventRow — план решения', () => {
  it('🔴 план свёрнут, но раскрывается по клику', () => {
    renderPlan();

    // Свёрнут: панель читают, чтобы видеть ход целиком, а план длиннее любого шага и
    // развёрнутым всегда вытеснил бы остальные строки.
    expect(screen.queryByText(/Прочитать резюме/)).toBeNull();

    fireEvent.click(screen.getByText('План готов: 3 шаг(ов)'));

    expect(screen.getByText(/Прочитать резюме/)).toBeInTheDocument();
  });

  it('🔴 текст плана виден ЦЕЛИКОМ, а не первой строкой', () => {
    // Обычная деталь шага режется до трёх строк — для плана это потеря содержания:
    // последние пункты и есть то, ради чего его смотрят.
    renderPlan();
    fireEvent.click(screen.getByText('План готов: 3 шаг(ов)'));

    const body = screen.getByText(/Прочитать резюме/);
    expect(body.textContent).toContain('3. Предложить правки');
  });

  it('обычный шаг сворачиваемым не становится', () => {
    render(
      <ChakraProvider>
        <TraceEventRow
          event={{ id: 'e1', kind: 'done', title: 'Выбран агент: general', detail: 'Маршрут определён' }}
        />
      </ChakraProvider>
    );

    // Деталь обычного шага видна сразу — сворачивание её не касается.
    expect(screen.getByText('Маршрут определён')).toBeInTheDocument();
  });
});
