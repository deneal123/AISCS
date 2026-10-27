import { act, renderHook } from '@testing-library/react';
import { normalizeAttachmentReferences, useChatMessageSender } from '../../../../src/features/chat/hooks/orchestration/useChatMessageSender';
import { sendChatMessage } from '@api/chat';

jest.mock('@api/chat', () => ({ sendChatMessage: jest.fn() }));


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
  it.each([null, { path: 'documents/paper', expected_revision: 'r1' }])('does not send a PDF request without its validated project identity: %j', async (documentContext) => {
    const props = { ...createProps(), documentContext, requireDocumentContext: true };
    const { result } = renderHook(() => useChatMessageSender(props));
    await act(async () => { await result.current.handleSendMessage('Уточни текст'); });
    expect(props.wsSendMessage).not.toHaveBeenCalled();
    expect(props.addMessage).not.toHaveBeenCalled();
    expect(props.startTraceSession).not.toHaveBeenCalled();
    expect(props.composerRef.current.clearInput).not.toHaveBeenCalled();
    expect(props.setError).toHaveBeenCalledWith(expect.stringContaining('Запрос не отправлен'));
  });
  it('preserves the PDF project anchor for the REST transport as well as WebSocket', async () => {
    sendChatMessage.mockResolvedValue({ reply: 'Готово', metadata: { document_project: 'owned-project' } });
    const props = { ...createProps(), attachments: [], useWebSocket: false, connectionState: 'disconnected',
      documentContext: { project_id: 'owned-project', path: 'documents/paper', expected_revision: 'r1' } };
    const { result } = renderHook(() => useChatMessageSender(props));
    await act(async () => { await result.current.handleSendMessage('Уточни текст'); });
    const users = props.addMessage.mock.calls.map(([message]) => message).filter((message) => message.type === 'user');
    expect(users).toHaveLength(1);
    expect(users[0].metadata).toEqual({ document_project: 'owned-project' });
    expect(sendChatMessage).toHaveBeenCalledTimes(1);
    expect(props.wsSendMessage).not.toHaveBeenCalled();
  });
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
      { confirmOfferId: 'opaque-offer-id', confirmationDecision: undefined },
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
