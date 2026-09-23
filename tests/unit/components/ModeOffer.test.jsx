import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { ChakraProvider } from '@chakra-ui/react';
import ModeOffer from '../../../src/features/chat/components/ModeOffer';

/**
 * Предложение дорогого режима.
 *
 * 🔴 Глубокое исследование и презентация стоят тысячи кредитов. Ошибка решателя там — не
 * «ответ вышел хуже», а списанные деньги, которых человек не просил. Поэтому «Авто»
 * отвечает обычным режимом, а дорогой предлагает кнопкой — решает человек.
 *
 * 🔴 И предложение ЖИВЁТ ОГРАНИЧЕННОЕ ВРЕМЯ, по СЕРВЕРНЫМ часам. Бессрочная кнопка либо
 * нажимается задним числом (через час, когда ответ прочитан и не нужен), либо мозолит
 * глаза. Срок несёт пара `offered_at`/`expires_in_sec` от сервера — здесь только
 * отображение остатка.
 */
const OFFER = {
  mode: 'deep_research',
  label: 'глубокое исследование',
  reason_code: 'confirmation_required',
  confidence: 'high',
  offered_at: new Date().toISOString(),
  expires_in_sec: 30,
};

const renderOffer = (offer, props = {}) =>
  render(
    <ChakraProvider>
      <ModeOffer offer={offer} onRun={props.onRunMode} disabled={props.isLoading} />
    </ChakraProvider>
  );

const runButton = () => screen.getByRole('button', { name: /Запустить/ });

describe('Предложение дорогого режима', () => {
  it('🔴 передаёт только opaque режим; текст даёт trace anchor', () => {
    const onRunMode = jest.fn();
    renderOffer(OFFER, { onRunMode });

    fireEvent.click(runButton());

    expect(onRunMode).toHaveBeenCalledWith(OFFER);
  });

  it('🔴 предупреждает о цене ДО нажатия', () => {
    // Иначе кнопка выглядит бесплатной, а стоит тысячи кредитов.
    renderOffer(OFFER, { onRunMode: jest.fn() });

    expect(screen.getByText(/платный режим/i)).toBeInTheDocument();
    expect(screen.getByText(/Дорогой режим ждёт подтверждения/)).toBeInTheDocument();
  });

  it('показывает полученную от сервера максимальную оценку и использует её в CTA', () => {
    renderOffer({ ...OFFER, offer_kind: 'tool', estimated_credits: 5_001 }, { onRunMode: jest.fn() });

    expect(screen.getByText(/Максимальная оценка.*5\s?001 кредитов/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Запустить за ~5\s?001/i })).toBeInTheDocument();
  });

  it('показывает, сколько осталось на решение', () => {
    renderOffer(OFFER, { onRunMode: jest.fn() });

    expect(screen.getByText(/На решение — \d+ с\./)).toBeInTheDocument();
  });

  it('без предложения ничего не рисуется', () => {
    renderOffer(undefined, { onRunMode: jest.fn() });

    expect(screen.queryByText(/Запустить/)).toBeNull();
  });

  it('во время ответа кнопка заблокирована', () => {
    // Второй дорогой прогон поверх идущего — это двойное списание по одному клику.
    renderOffer(OFFER, { onRunMode: jest.fn(), isLoading: true });

    expect(runButton()).toBeDisabled();
  });

  it('без обработчика кнопка не активна', () => {
    // Гостю или на экране без отправки кнопка вела бы в никуда.
    renderOffer(OFFER);

    expect(runButton()).toBeDisabled();
  });

  // --- срок жизни ----------------------------------------------------------------

  it('🔴 просроченное сервером предложение — НЕ кнопка, а видимый след отказа', () => {
    // Исчезнувшая карточка неотличима от «предложения не было»; человеку нужно понимать,
    // что режим предлагался и был отклонён молчанием.
    renderOffer({ ...OFFER, expired: true }, { onRunMode: jest.fn() });

    expect(screen.queryByText(/Запустить/)).toBeNull();
    expect(screen.getByText(/отклонён по таймауту/)).toBeInTheDocument();
  });

  it('🔴 истёкший срок гасит кнопку и без отметки сервера', () => {
    // Вторая вкладка и перезагрузка не воскрешают рычаг: остаток считается от серверного
    // `offered_at`, а не от момента открытия страницы.
    const stale = { ...OFFER, offered_at: new Date(Date.now() - 120_000).toISOString() };
    renderOffer(stale, { onRunMode: jest.fn() });

    expect(screen.queryByText(/Запустить/)).toBeNull();
    expect(screen.getByText(/отклонён по таймауту/)).toBeInTheDocument();
  });

  it('честно сообщает, что дорогой запуск после истечения не выполнялся', () => {
    renderOffer({
      ...OFFER,
      mode: 'expensive_run',
      offer_kind: 'tool',
      expired: true,
    }, { onRunMode: jest.fn() });

    expect(screen.getByText('Срок подтверждения истёк, запуск не выполнялся.')).toBeInTheDocument();
    expect(screen.queryByText(/ответ дан без него/)).not.toBeInTheDocument();
  });

  it('🔴 предложение без серверной метки времени живым не считается', () => {
    // Иначе «бессрочная кнопка» вернулась бы через любую запись, где срока нет.
    const { offered_at: _drop, ...noStamp } = OFFER;
    renderOffer(noStamp, { onRunMode: jest.fn() });

    expect(screen.queryByText(/Запустить/)).toBeNull();
  });
});

describe('ModeOffer — предложение ИНСТРУМЕНТА, а не режима', () => {
  const toolOffer = {
    offer_kind: 'tool',
    mode: 'watch_video',
    label: 'просмотр видео',
    reason_code: 'video_confirmation_required',
    offered_at: new Date().toISOString(),
    expires_in_sec: 30,
  };

  it('🔴 принятие отправляет РОД предложения — иначе клиент пошлёт несуществующий маршрут', () => {
    const onRun = jest.fn();
    render(
      <ChakraProvider>
        <ModeOffer offer={toolOffer} onRun={onRun} />
      </ChakraProvider>
    );

    fireEvent.click(screen.getByText(/Запустить/));

    expect(onRun).toHaveBeenCalledWith(toolOffer);
  });

  it('не называет инструмент режимом', () => {
    render(
      <ChakraProvider>
        <ModeOffer offer={toolOffer} onRun={() => {}} />
      </ChakraProvider>
    );

    expect(screen.getByText(/Могу включить/)).toBeInTheDocument();
    expect(screen.queryByText(/Подошёл бы режим/)).not.toBeInTheDocument();
  });

  it('🔴 РЕЖИМ по-прежнему предлагается как режим — иначе «починили» одно, сломав другое', () => {
    const onRun = jest.fn();
    render(
      <ChakraProvider>
        <ModeOffer
          offer={{ ...toolOffer, offer_kind: undefined, mode: 'deep_research', label: 'исследование' }}
          onRun={onRun}
        />
      </ChakraProvider>
    );

    expect(screen.getByText(/Подошёл бы режим/)).toBeInTheDocument();
    fireEvent.click(screen.getByText(/Запустить/));
    expect(onRun).toHaveBeenCalledWith(expect.objectContaining({ mode: 'deep_research' }));
  });

  it('принятое сервером предложение не превращается в отклонённое после TTL', () => {
    render(
      <ChakraProvider>
        <ModeOffer
          offer={{
            ...toolOffer,
            offered_at: new Date(Date.now() - 120_000).toISOString(),
            status: 'accepted',
          }}
          onRun={() => {}}
        />
      </ChakraProvider>
    );

    expect(screen.getByText(/Подтверждено, запуск начат/)).toBeInTheDocument();
    expect(screen.queryByText(/отклонён по таймауту/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('локальный клик показывает отправку, но не выдаёт её за серверное принятие', () => {
    const onRun = jest.fn();
    render(
      <ChakraProvider>
        <ModeOffer offer={toolOffer} onRun={onRun} />
      </ChakraProvider>
    );

    fireEvent.click(screen.getByRole('button'));

    expect(screen.getByText(/Подтверждение отправлено/)).toBeInTheDocument();
    expect(screen.queryByText(/Подтверждено, запуск начат/)).not.toBeInTheDocument();
    expect(screen.queryByText(/отклонён по таймауту/)).not.toBeInTheDocument();
  });
});
