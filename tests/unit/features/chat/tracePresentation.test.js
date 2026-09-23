import { getAgentLabel, getOmissionReason, getTraceName } from '@features/chat/utils/trace';

describe('представление событий trace', () => {
  it('переводит известные технические имена и причины для русской аудитории', () => {
    expect(getTraceName('web_search')).toBe('Веб-поиск');
    expect(getAgentLabel('general')).toBe('Основной');
    expect(getOmissionReason('needs_confirmation')).toBe('нужно ваше согласие');
    expect(getOmissionReason('not_in_tier')).toContain('следующем шаге');
  });

  it('не оставляет неизвестный идентификатор в машинном snake_case', () => {
    expect(getTraceName('custom_remote_tool')).toBe('«custom remote tool»');
  });
});
