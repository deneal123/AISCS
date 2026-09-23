import { offerSendOptions } from '../../../../src/features/chat/model/offerAcceptance';

/**
 * 🔴 ПРЕДЛОЖЕНИЯ БЫВАЮТ ДВУХ РОДОВ, и принимаются они по-разному. Режим перезапускает
 * прогон другим маршрутом; инструмент маршрут не меняет — он снимает запор с признака
 * контекста. Отправив имя инструмента как маршрут, клиент послал бы значение, которого
 * среди маршрутов нет: бэкенд отверг бы запрос схемой, а человек увидел бы, что кнопка не
 * работает, без единого объяснения.
 */
describe('принятие предложения', () => {
  it('🔴 инструмент отправляется ПРИЗНАКОМ СОГЛАСИЯ, а не маршрутом', () => {
    expect(offerSendOptions('watch_video', 'tool')).toEqual({ watchVideo: true });
  });

  it('🔴 режим по-прежнему отправляется маршрутом — иначе «починили» одно, сломав другое', () => {
    expect(offerSendOptions('deep_research')).toEqual({ routeOverride: 'deep_research' });
    expect(offerSendOptions('pptx_gen', 'route')).toEqual({ routeOverride: 'pptx_gen' });
  });

  it('незнакомый инструмент не превращается в несуществующий маршрут', () => {
    // ⚠️ Пустые опции = «отправить обычным сообщением»: ответ будет, просто без дорогой
    // способности. Маршрут с неизвестным именем отверг бы схему, и кнопка молча умерла бы.
    expect(offerSendOptions('watch_hologram', 'tool')).toEqual({});
  });

  it('пустое имя не роняет обработчик', () => {
    expect(offerSendOptions(undefined, 'tool')).toEqual({});
    expect(offerSendOptions(null)).toEqual({ routeOverride: '' });
  });

  it('дорогой запуск подтверждается только opaque offer id без повторного текста', () => {
    expect(offerSendOptions({
      mode: 'expensive_run',
      offer_kind: 'tool',
      offer_id: 'opaque-confirmation-anchor',
    })).toEqual({
      confirmOfferId: 'opaque-confirmation-anchor',
      skipUserAppend: true,
    });
  });
});
