import {
  creditBarView,
  creditLevel,
  eventLabel,
  formatCredits,
  formatRub,
  planLabel,
} from '@features/billing/lib/credits';

// ru-RU использует неразрывный пробел (U+00A0) как разделитель групп.
// Чтобы сравнения не зависели от вида пробела, выкидываем все пробелы.
const stripSpaces = (value) => String(value).replace(/\s/g, '');

describe('billing credits lib', () => {
  it('formats credits with ru grouping and guards negatives', () => {
    expect(stripSpaces(formatCredits(1234567))).toBe('1234567');
    expect(formatCredits(-5)).toBe('0');
    expect(formatCredits(undefined)).toBe('0');
  });

  it('formats rubles', () => {
    expect(stripSpaces(formatRub(990))).toBe('990₽');
  });

  it('labels plans', () => {
    expect(planLabel('pro')).toBe('Pro');
    expect(planLabel('free')).toBe('Free');
    expect(planLabel(undefined)).toBe('Free');
    expect(planLabel('custom')).toBe('custom');
  });

  // ⚠️ Полоса показывает ОСТАТОК, а не расход: она пустеет по мере трат, а
  // компонент подписывает её «N осталось» (CreditBar.jsx). Тест был написан под
  // прежнюю семантику «сколько израсходовано» и после перехода на гейдж остатка
  // не обновился — то есть закреплял поведение, которого в продукте уже нет.
  // Цвета при этом не менялись: порог считается от ОСТАТКА (≤25% — оранжевый,
  // ≤5% — красный), поэтому в старых строках совпадали именно цвета, а числа нет.
  it('computes credit bar percent and color from the REMAINING share', () => {
    expect(creditBarView(0, 100)).toEqual({ percent: 100, color: '#2D5BFF' }); // ничего не потрачено — полная
    expect(creditBarView(50, 100)).toEqual({ percent: 50, color: '#2D5BFF' });
    expect(creditBarView(85, 100)).toEqual({ percent: 15, color: '#f59e0b' }); // осталось 15% — мало
    expect(creditBarView(100, 100)).toEqual({ percent: 0, color: '#ef4444' }); // пусто
    expect(creditBarView(150, 100)).toEqual({ percent: 0, color: '#ef4444' }); // перерасход не уводит в минус
    expect(creditBarView(10, 0)).toEqual({ percent: 0, color: '#2D5BFF' }); // лимита нет — полосе нечего показывать
  });

  it('classifies credit level for the composer indicator', () => {
    expect(creditLevel(0)).toBe('empty');
    expect(creditLevel(-10)).toBe('empty');
    expect(creditLevel(1000)).toBe('low');
    expect(creditLevel(50000)).toBe('ok');
    expect(creditLevel(3000, 2000)).toBe('ok');
  });

  it('labels billing event types', () => {
    expect(eventLabel('usage')).toBe('Списание');
    expect(eventLabel('topup')).toBe('Пополнение');
    expect(eventLabel('unknown')).toBe('unknown');
  });
});
