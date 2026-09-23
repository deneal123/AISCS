import { buildConversationMarkdown } from '@features/chat/utils/exportThread';

describe('buildConversationMarkdown', () => {
  const messages = [
    { type: 'user', content: 'Привет', timestamp: '2026-07-06T10:00:00Z' },
    {
      type: 'agent',
      content: '<think>rough</think>Здравствуйте!',
      timestamp: '2026-07-06T10:00:05Z',
      metadata: { selected_model: 'openai/gpt-4o' },
    },
  ];

  it('includes the title and both turns', () => {
    const md = buildConversationMarkdown(messages, 'Мой чат');
    expect(md).toContain('# Мой чат');
    expect(md).toContain('Пользователь');
    expect(md).toContain('Привет');
    expect(md).toContain('Ассистент');
    expect(md).toContain('openai/gpt-4o');
  });

  it('strips <think> reasoning from assistant content', () => {
    const md = buildConversationMarkdown(messages, 'X');
    expect(md).toContain('Здравствуйте!');
    expect(md).not.toContain('rough');
    expect(md).not.toContain('<think>');
  });

  it('skips empty messages', () => {
    const md = buildConversationMarkdown([{ type: 'user', content: '' }], 'X');
    expect(md).not.toContain('Пользователь');
  });
});
