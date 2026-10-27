import { act, renderHook, waitFor } from '@testing-library/react';
import { useChatCapabilities } from '../../../../src/features/chat/hooks/orchestration/useChatCapabilities';
import { getChatModelsCatalogCached, getChatModelsCached, getChatPersonas, getTranscriptionConfig, resetChatModelsCache } from '../../../../src/shared/api/chat';

jest.mock('../../../../src/shared/api/chat', () => ({
  getChatModelsCatalogCached: jest.fn(), getChatModelsCached: jest.fn(),
  getChatPersonas: jest.fn(), getTranscriptionConfig: jest.fn(), resetChatModelsCache: jest.fn(),
}));

beforeEach(() => {
  jest.clearAllMocks();
  getChatPersonas.mockResolvedValue({ personas: [] });
  getTranscriptionConfig.mockResolvedValue(null);
});

it('never silently resets a manual model after a successful incompatible catalog', async () => {
  getChatModelsCatalogCached.mockResolvedValue({ models: [{ id: 'other' }] });
  const invalid = jest.fn();
  const { result } = renderHook(() => useChatCapabilities({ selectedModel: 'manual', onInvalidModel: invalid }));
  await waitFor(() => expect(result.current.modelsStatus).toBe('ready'));
  expect(invalid).not.toHaveBeenCalled();
});

it('retains cached models during refresh failure and exposes an explicit retry', async () => {
  getChatModelsCatalogCached.mockResolvedValueOnce({ models: [{ id: 'GigaChat-2' }] }).mockRejectedValueOnce(new Error('unavailable')).mockResolvedValueOnce({ models: [] });
  getChatModelsCached.mockRejectedValue(new Error('unavailable'));
  const { result } = renderHook(() => useChatCapabilities());
  await waitFor(() => expect(result.current.modelsStatus).toBe('ready'));
  await act(async () => result.current.refreshModels());
  expect(result.current.modelsStatus).toBe('error');
  expect(result.current.availableModels).toEqual(['GigaChat-2']);
  await act(async () => result.current.refreshModels());
  expect(result.current.modelsStatus).toBe('ready');
  expect(result.current.availableModels).toEqual([]);
  expect(resetChatModelsCache).toHaveBeenCalledTimes(2);
});

it('ignores older model responses after a retry', async () => {
  let resolve;
  getChatModelsCatalogCached.mockReturnValueOnce(new Promise((done) => { resolve = done; })).mockResolvedValueOnce({ models: [{ id: 'new' }] });
  const { result } = renderHook(() => useChatCapabilities());
  await waitFor(() => expect(getChatModelsCatalogCached).toHaveBeenCalledTimes(1));
  await act(async () => result.current.refreshModels());
  await act(async () => resolve({ models: [{ id: 'old' }] }));
  expect(result.current.availableModels).toEqual(['new']);
});

it('does not interpret malformed discovery as an authoritative empty catalog', async () => {
  getChatModelsCatalogCached.mockResolvedValue({ models: [{ title: 'not an id' }] });
  getChatModelsCached.mockResolvedValue({ models: [] });
  const { result } = renderHook(() => useChatCapabilities());
  await waitFor(() => expect(result.current.modelsStatus).toBe('error'));
});

it('distinguishes missing research metadata from a usable chat model list and retries it', async () => {
  getChatModelsCatalogCached.mockRejectedValueOnce(new Error('catalog unavailable'))
    .mockResolvedValueOnce({ models: [{ id: 'GigaChat-2', capabilities: ['tools'] }] });
  getChatModelsCached.mockResolvedValue(['GigaChat-2']);
  const { result } = renderHook(() => useChatCapabilities());
  await waitFor(() => expect(result.current.modelsStatus).toBe('ready'));
  expect(result.current.modelCatalogStatus).toBe('error');
  expect(result.current.availableModels).toEqual(['GigaChat-2']);
  await act(async () => result.current.refreshModels());
  expect(result.current.modelCatalogStatus).toBe('ready');
  expect(result.current.modelCatalog['GigaChat-2'].capabilities).toContain('tools');
});

it('preserves last known metadata on a rich-catalog failure without retaining removed models', async () => {
  const model = { id: 'GigaChat-2', capabilities: ['tools'] };
  getChatModelsCatalogCached.mockResolvedValueOnce({ models: [model, { id: 'removed', capabilities: ['tools'] }] })
    .mockRejectedValueOnce(new Error('unavailable'));
  getChatModelsCached.mockResolvedValue(['GigaChat-2']);
  const { result } = renderHook(() => useChatCapabilities());
  await waitFor(() => expect(result.current.modelsStatus).toBe('ready'));
  await act(async () => result.current.refreshModels());
  expect(result.current.modelCatalogStatus).toBe('error');
  expect(result.current.modelCatalog).toEqual({ 'GigaChat-2': model });
});
