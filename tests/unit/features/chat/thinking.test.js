import { parseThinking, stripThinking } from '@features/chat/utils/thinking';

describe('parseThinking', () => {
  it('splits a closed <think> block from the visible answer', () => {
    const raw = '<think>reasoning here</think>Привет! Всё отлично.';
    const { visible, reasoning } = parseThinking(raw);
    expect(visible).toBe('Привет! Всё отлично.');
    expect(reasoning).toBe('reasoning here');
  });

  it('handles an unclosed <think> during streaming (visible stays empty)', () => {
    const raw = '<think>still thinking, no answer yet';
    const { visible, reasoning } = parseThinking(raw);
    expect(visible).toBe('');
    expect(reasoning).toBe('still thinking, no answer yet');
  });

  it('collects multiple think blocks and preserves surrounding text', () => {
    const raw = 'A<think>one</think>B<think>two</think>C';
    const { visible, reasoning } = parseThinking(raw);
    expect(visible).toBe('ABC');
    expect(reasoning).toBe('one\n\ntwo');
  });

  it('returns content unchanged when there is no <think> tag', () => {
    expect(parseThinking('plain answer')).toEqual({ visible: 'plain answer', reasoning: '' });
  });

  it('stripThinking returns only the visible part', () => {
    expect(stripThinking('<think>x</think>answer')).toBe('answer');
    expect(stripThinking(null)).toBe('');
  });
});
