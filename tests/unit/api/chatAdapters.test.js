import { login, registerUser, logoutLocal } from '@/shared/api/auth';
import { acquireWorkspaceLease, createChatThread, getChatModels, sendChatMessage, uploadChatFile, uploadFileToWorkspace } from '@/shared/api/chat';
import { mapApiError, mapChatUploadResponse } from '@/shared/api/dtoMappers';
import { request } from '@/shared/api/request';

jest.mock('@/shared/api/request', () => ({
  request: jest.fn(),
}));

describe('API adapters', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('login delegates to unified request client', async () => {
    request.mockResolvedValue({ token: 't' });
    const payload = { email: 'a@a.com', password: 'p' };

    await expect(login(payload)).resolves.toEqual({ token: 't' });
    expect(request).toHaveBeenCalledWith({ method: 'post', url: '/api/auth/v1/login', data: payload });
  });

  it('registerUser delegates payload to unified request client', async () => {
    const payload = { email: 'user@test.dev', password: 'pass' };
    request.mockResolvedValue({ user_id: 'u1' });

    await expect(registerUser(payload)).resolves.toEqual({ user_id: 'u1' });
    expect(request).toHaveBeenCalledWith({ method: 'post', url: '/api/auth/v1/register', data: payload });
  });

  it('createChatThread sends optional user id', async () => {
    request.mockResolvedValue({ thread_id: 'th_1' });

    await createChatThread('user-1');

    expect(request).toHaveBeenCalledWith({ method: 'post', url: '/api/chats/', data: { user_id: 'user-1' } });
  });

  it('sendChatMessage maps options to transport payload', async () => {
    request.mockResolvedValue({ reply: 'ok' });

    await sendChatMessage('th_1', ' hello ', 'user-1', 'gpt', 'text', {
      webSearch: true,
      deepResearch: true,
      fileContext: 'context',
      fileIds: ['f1'],
      routeOverride: 'analysis',
      confirmExpensiveRun: true,
    });

    expect(request).toHaveBeenCalledWith({
      method: 'post',
      url: '/api/chats/th_1/message',
      data: {
        text: 'hello',
        user_id: 'user-1',
        model: 'gpt',
        input_type: 'text',
        web_search: true,
        deep_research: true,
        file_context: 'context',
        file_ids: ['f1'],
        route_override: 'analysis',
        confirm_expensive_run: true,
      },
    });
  });

  it('getChatModels returns empty array fallback', async () => {
    request.mockResolvedValue([]);
    await expect(getChatModels()).resolves.toEqual([]);
  });

  it('keeps transcription options in the chat-upload form rather than axios options', async () => {
    request.mockResolvedValue({ file_id: 'opaque-id' });
    const file = new File(['audio'], 'note.mp3', { type: 'audio/mpeg' });

    await uploadChatFile(file, 'thread-1', undefined, {
      transcriptionMode: 'local',
      transcriptionModel: 'small',
      uploadIntentId: '11111111-1111-4111-8111-111111111111',
    });

    const [config] = request.mock.calls[0];
    expect(config.data.get('thread_id')).toBe('thread-1');
    expect(config.data.get('transcription_mode')).toBe('local');
    expect(config.data.get('transcription_model')).toBe('small');
    expect(config.data.get('upload_intent_id')).toBe('11111111-1111-4111-8111-111111111111');
    expect(config.transcriptionMode).toBeUndefined();
  });

  it('sends a Work upload using only file, revision, fence and opaque intent', async () => {
    request.mockResolvedValue({ outcome: 'imported', revision: 'r2' });
    const file = new File(['brief'], 'brief.txt', { type: 'text/plain' });

    await uploadFileToWorkspace('thread-1', file, 'r1', 4, undefined, {
      uploadIntentId: '22222222-2222-4222-8222-222222222222',
    });

    const [config] = request.mock.calls[0];
    expect(config.url).toBe('/api/chats/thread-1/work/upload');
    expect(config.data.get('expected_revision')).toBe('r1');
    expect(config.data.get('fence')).toBe('4');
    expect(config.data.get('upload_intent_id')).toBe('22222222-2222-4222-8222-222222222222');
    expect(config.data.get('file').name).toBe('brief.txt');
    expect(JSON.stringify(config)).not.toContain('storage');
    expect(JSON.stringify(config)).not.toContain('capability');
  });

  it('separates editor tabs with an opaque workspace session header', async () => {
    request.mockResolvedValue({ fence: 9 });

    await acquireWorkspaceLease('thread-1', 'brief.txt', {
      actorSession: '11111111-1111-4111-8111-111111111111',
    });

    expect(request).toHaveBeenCalledWith(expect.objectContaining({
      data: { path: 'brief.txt' },
      headers: { 'X-Workspace-Session': '11111111-1111-4111-8111-111111111111' },
    }));
  });

  it('rejects an upload response with no durable UserFile id', () => {
    expect(() => mapChatUploadResponse({ filename: 'phantom.txt' })).toThrow(
      /не был сохранён в библиотеке/i,
    );
  });

  it('mapApiError returns typed domain error', () => {
    const error = { response: { status: 401, data: { code: 'UNAUTHORIZED', detail: 'invalid credentials' } } };
    expect(mapApiError(error)).toMatchObject({
      type: 'DomainError',
      status: 401,
      code: 'UNAUTHORIZED',
      isRetryable: false,
      isCanceled: false,
    });
  });

  it('logoutLocal clears auth cookie', () => {
    // jsdom не хранит протухшую cookie, поэтому проверяем сам факт записи
    // удаляющей cookie (auth_token=; expires=<прошлое>) через перехват сеттера.
    const writes = [];
    const original = Object.getOwnPropertyDescriptor(document, 'cookie');
    Object.defineProperty(document, 'cookie', {
      configurable: true,
      get: () => writes.join('; '),
      set: (value) => { writes.push(value); },
    });
    try {
      logoutLocal();
      expect(writes.some((w) => w.includes('auth_token=;'))).toBe(true);
    } finally {
      if (original) Object.defineProperty(document, 'cookie', original);
    }
  });
});
