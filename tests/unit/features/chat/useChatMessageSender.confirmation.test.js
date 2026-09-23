import { act, renderHook } from '@testing-library/react';
import { normalizeAttachmentReferences, useChatMessageSender } from '../../../../src/features/chat/hooks/orchestration/useChatMessageSender';


function createProps() {
  return {
    addMessage: jest.fn(),
    appendTraceEvent: jest.fn(),
    attachments: [{ filename: 'materials.md', extracted_text: 'PRIVATE' }],
    isFileUploading: false,
    clearError: jest.fn(),
    clearAttachments: jest.fn(),
    consumeUserDetached: jest.fn(() => false),
    composerRef: { current: { clearInput: jest.fn() } },
    connectionState: 'connected',
    deepResearchEnabled: false,
    ensureGuestLimit: jest.fn(() => true),
    finalizeTraceSession: jest.fn(),
    forcedRoute: null,
    incrementRequests: jest.fn(),
    initialFileContext: '',
    initialInputType: 'text',
    initialManualModel: 'GigaChat-2',
    isAuthenticated: true,
    resolveSessionUserId: jest.fn(() => 'user'),
    selectedModelOverride: null,
    setError: jest.fn(),
    setIsLoading: jest.fn(),
    setSidebarSearch: jest.fn(),
    showAuthModal: jest.fn(),
    sideEffects: { notify: jest.fn() },
    startTraceSession: jest.fn(() => 'trace-1'),
    threadId: 'thread-1',
    upsertRecentThread: jest.fn(),
    useWebSocket: true,
    voiceText: '',
    onVoiceConsumed: jest.fn(),
    webSearchEnabled: false,
    wsSendMessage: jest.fn(),
  };
}


describe('useChatMessageSender confirmation anchor', () => {
  it('restores safe persisted attachment identities without inventing content', () => {
    expect(normalizeAttachmentReferences([{
      filename: 'materials.md',
      file_type: 'document',
      file_id: 'owned-file',
      mime_type: 'text/markdown',
      digest: 'a'.repeat(64),
    }])).toEqual([{
      filename: 'materials.md',
      file_type: 'document',
      file_id: 'owned-file',
      mime_type: 'text/markdown',
      content_sha256: 'a'.repeat(64),
    }]);
  });

  it('sends only the offer id and never appends a duplicate user message', async () => {
    const props = createProps();
    const { result } = renderHook(() => useChatMessageSender(props));

    await act(async () => {
      await result.current.handleSendMessage('', {
        confirmOfferId: 'opaque-offer-id',
        skipUserAppend: true,
        anchorMessageId: 'original-user-message',
      });
    });

    expect(props.wsSendMessage).toHaveBeenCalledTimes(1);
    expect(props.wsSendMessage).toHaveBeenCalledWith(
      '',
      null,
      null,
      { confirmOfferId: 'opaque-offer-id' },
    );
    expect(props.addMessage).not.toHaveBeenCalled();
    expect(props.clearAttachments).not.toHaveBeenCalled();
    expect(props.composerRef.current.clearInput).not.toHaveBeenCalled();
    expect(props.upsertRecentThread).not.toHaveBeenCalled();
  });

  it('keeps text attachments available without forcing the general route', async () => {
    const props = createProps();
    const { result } = renderHook(() => useChatMessageSender(props));

    await act(async () => {
      await result.current.handleSendMessage('Напиши статью в PDF');
    });

    expect(props.wsSendMessage).toHaveBeenCalledTimes(1);
    const [, model, inputType, options] = props.wsSendMessage.mock.calls[0];
    expect(model).toBe('GigaChat-2');
    expect(inputType).toBe('text');
    expect(options).not.toHaveProperty('routeOverride');
    expect(options.attachments).toEqual([
      expect.objectContaining({ name: 'materials.md', content: 'PRIVATE' }),
    ]);
  });
});
