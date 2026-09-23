import { feedbackKey } from '@features/chat/utils/feedbackKey';

describe('feedbackKey (mirrors backend feedback_store.feedback_key)', () => {
  it('produces the same fixed hashes as the Python side', () => {
    expect(feedbackKey('test')).toBe('afd071e5');
    expect(feedbackKey('ab')).toBe('4d2505ca');
    expect(feedbackKey('hello world')).toBe('d58b3fa7');
  });

  it('trims before hashing', () => {
    expect(feedbackKey('  test  ')).toBe(feedbackKey('test'));
  });

  it('handles cyrillic (UTF-8 bytes) consistently', () => {
    // Совпадает с backend feedback_key("Здравствуйте!") == "8bcb6146".
    expect(feedbackKey('Здравствуйте!')).toBe('8bcb6146');
  });
});
