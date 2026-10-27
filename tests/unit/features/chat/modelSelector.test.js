import {
  parseModelMeta,
  resolveMessageModelLabel,
  sortModelsByProvider,
  currentLocalModel,
} from '@features/chat/utils/modelSelector';
import { normalizeChatUiSettings } from '@features/chat/schema/chatUiSettingsSchema';

it('обновляет будущий локальный выбор, не меняя облачные ID и историю расхода', () => {
  expect(currentLocalModel('lfm2.5-1.2b-instruct')).toBe('qwen2.5-1.5b-instruct');
  expect(currentLocalModel('liquid/lfm2.5-1.2b-instruct')).toBe('liquid/lfm2.5-1.2b-instruct');
  expect(currentLocalModel('')).toBe('');
  const saved = { preferredModel: 'lfm2.5-1.2b-instruct', ldrModel: 'openai/gpt-4o' };
  const updated = normalizeChatUiSettings(saved);
  expect(updated.preferredModel).toBe('qwen2.5-1.5b-instruct');
  expect(updated.ldrModel).toBe('openai/gpt-4o');
  expect(saved.preferredModel).toBe('lfm2.5-1.2b-instruct');
  expect(resolveMessageModelLabel({ metadata: { usage: { actual_model: 'lfm2.5-1.2b-instruct' } } }))
    .toBe('lfm2.5-1.2b-instruct');
  expect(parseModelMeta(updated.preferredModel).label).toBe('Qwen2.5 · 1.5B');
});

describe('parseModelMeta — provider detection', () => {
  it('splits "provider/model" ids', () => {
    const m = parseModelMeta('openai/gpt-4o');
    expect(m.provider).toBe('openai');
    expect(m.providerLabel).toBe('OpenAI');
    expect(m.label).toBe('gpt-4o');
  });

  it('detects GigaChat from a bare id (no separator)', () => {
    const m = parseModelMeta('GigaChat');
    expect(m.provider).toBe('gigachat');
    expect(m.providerLabel).toBe('GigaChat');
  });

  it('detects GigaChat / MWS from a dash-prefixed id', () => {
    expect(parseModelMeta('GigaChat-Pro').provider).toBe('gigachat');
    expect(parseModelMeta('mws-gpt-alpha').provider).toBe('mws');
  });

  it('leaves an unknown bare id without a provider', () => {
    const m = parseModelMeta('some-random-model');
    expect(m.provider).toBeNull();
    expect(m.label).toBe('some-random-model');
  });
});

describe('resolveMessageModelLabel', () => {
  it('uses the actual authoring model for document runs', () => {
    expect(resolveMessageModelLabel({
      metadata: {
        actual_authoring_model: 'GigaChat-2',
        selected_model: 'openai/gpt-4o',
        usage: { actual_model: 'openai/gpt-4o' },
      },
    })).toBe('GigaChat-2');
  });

  it('prefers the actually billed model over a stale requested label', () => {
    expect(resolveMessageModelLabel({
      metadata: {
        selected_model: 'openai/gpt-4o',
        usage: { model: 'GigaChat-3-Lightning', actual_model: 'GigaChat-3-Lightning' },
      },
    })).toBe('GigaChat-3-Lightning');
  });

  it('restores the persisted usage model when selected_model is absent', () => {
    expect(resolveMessageModelLabel({
      metadata: { usage: { model: 'GigaChat-3-Lightning' } },
    })).toBe('GigaChat-3-Lightning');
  });
});

describe('sortModelsByProvider — domestic providers first', () => {
  it('puts the local model before all cloud models without inventing other local aliases', () => {
    expect(sortModelsByProvider(['GigaChat-2', 'openai/gpt-4o', 'qwen2.5-1.5b-instruct'])[0])
      .toBe('qwen2.5-1.5b-instruct');
    expect(parseModelMeta('qwen2.5-1.5b-instruct').providerLabel).toBe('Локальная модель');
    expect(parseModelMeta('liquid/lfm2.5-1.2b-instruct').provider).not.toBe('local');
  });
  it('surfaces GigaChat/MWS ahead of foreign providers regardless of alphabet', () => {
    const sorted = sortModelsByProvider([
      'anthropic/claude-3',
      'ai21/jamba-large',
      'GigaChat',
      'GigaChat-Pro',
      'mws-gpt-alpha',
      'openai/gpt-4o',
    ]);
    // gigachat → mws → yandexgpt приоритет; всё остальное после
    expect(sorted.slice(0, 3)).toEqual(['GigaChat', 'GigaChat-Pro', 'mws-gpt-alpha']);
    expect(sorted.indexOf('GigaChat')).toBeLessThan(sorted.indexOf('anthropic/claude-3'));
  });
});
