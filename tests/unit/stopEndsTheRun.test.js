/**
 * Кнопка «стоп» останавливает даже МЁРТВЫЙ прогон.
 *
 * 🔴 ЖИВОЙ КАДР. Трейс замер на «Запрос принят · 1 шаг», надпись «Готовлю ответ…»
 * крутилась, стоп не останавливал. Два независимых изъяна в одном обработчике:
 *
 * 1. Интерфейс гасился только в `finally`, ПОСЛЕ похода в ручку отмены (потолок 30 с).
 *    Человек жмёт «стоп» ровно тогда, когда исполнителя может уже не быть, — ждать от
 *    него подтверждения нельзя.
 * 2. Сессия трейса не финализировалась НИКЕМ: спиннер композера гас, а панель хода
 *    оставалась в «Готовлю ответ…» навсегда.
 *
 * ⚠️ Проверяем ПОРЯДОК в исходнике, а не отрендеренный контейнер: рендер страницы чата
 * тянет роутер, стор, WS и десяток провайдеров — страж превратился бы в тест окружения.
 */
import fs from 'fs';
import path from 'path';

const SOURCE = fs.readFileSync(
  path.join(__dirname, '../../src/features/chat/page/ChatPageContainer.jsx'),
  'utf8'
);

function cancelHandlerBody() {
  const start = SOURCE.indexOf('const handleCancelJob = useCallback(');
  expect(start).toBeGreaterThan(-1);
  const end = SOURCE.indexOf('}, [', start);
  expect(end).toBeGreaterThan(start);
  return SOURCE.slice(start, end);
}

describe('остановка генерации', () => {
  it('гасит интерфейс ДО похода в сеть', () => {
    const body = cancelHandlerBody();
    const stopsSpinner = body.indexOf('setIsLoading(false)');
    const network = body.indexOf('await cancelJob(');

    expect(stopsSpinner).toBeGreaterThan(-1);
    expect(network).toBeGreaterThan(-1);
    expect(stopsSpinner).toBeLessThan(network);
  });

  it('закрывает сессию трейса, а не оставляет «Готовлю ответ…»', () => {
    const body = cancelHandlerBody();

    expect(body).toContain('finalizeTraceSession(');
    expect(body).toContain('Остановлено пользователем');
  });

  it('сбой ручки отмены не отменяет остановку интерфейса', () => {
    const body = cancelHandlerBody();
    const tryAt = body.indexOf('try {');
    const stopsSpinner = body.indexOf('setIsLoading(false)');

    // Остановка стоит ВНЕ try: исключение из сети её больше не пропускает.
    expect(stopsSpinner).toBeLessThan(tryAt);
  });
});
