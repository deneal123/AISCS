import { act, renderHook } from '@testing-library/react';
import { useMessageActions } from '@features/chat/hooks/useMessageActions';

describe('document retry', () => {
  it('replays the original safe attachment references exactly once', () => {
    const attachment = {
      filename: 'materials.md',
      file_type: 'document',
      file_id: 'owned-file',
      mime_type: 'text/markdown',
      digest: 'a'.repeat(64),
    };
    const messages = [
      { id: 'user-1', type: 'user', content: 'Напиши статью', attachments: [attachment] },
      { id: 'agent-1', type: 'agent', content: 'Черновик сохранён' },
    ];
    const replaceMessages = jest.fn();
    const send = jest.fn();
    const { result } = renderHook(() => useMessageActions({
      messages,
      replaceMessages,
      handleSendMessageRef: { current: send },
    }));

    act(() => result.current.regenerateMessage('agent-1'));

    expect(replaceMessages).toHaveBeenCalledWith([messages[0]]);
    expect(send).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenCalledWith('Напиши статью', {
      skipUserAppend: true,
      anchorMessageId: 'user-1',
      attachmentRefs: [attachment],
    });
  });

  it('allows only the closed research document route for an evidence retry', () => {
    const messages = [
      { id: 'user-1', type: 'user', content: 'Напиши статью', attachments: [] },
      { id: 'agent-1', type: 'agent', content: 'Нужны источники' },
    ];
    const send = jest.fn();
    const { result } = renderHook(() => useMessageActions({
      messages,
      replaceMessages: jest.fn(),
      handleSendMessageRef: { current: send },
    }));

    act(() => result.current.regenerateMessage(
      'agent-1',
      undefined,
      'research_pdf_document',
    ));

    expect(send).toHaveBeenCalledWith('Напиши статью', expect.objectContaining({
      routeOverride: 'research_pdf_document',
      attachmentRefs: [],
    }));
  });
});
