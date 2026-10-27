import { getChatModelsCatalogCached, getChatModelsCached, resetChatModelsCache } from '../../../src/shared/api/chat';
import { request } from '../../../src/shared/api/request';

jest.mock('../../../src/shared/api/request', () => ({ request: jest.fn() }));

beforeEach(() => { jest.clearAllMocks(); resetChatModelsCache(); });

it('shares discovery until an explicit invalidation', async () => {
  request.mockResolvedValue({ models: [] });
  const first = getChatModelsCatalogCached();
  expect(getChatModelsCatalogCached()).toBe(first);
  await first;
  resetChatModelsCache();
  expect(getChatModelsCatalogCached()).not.toBe(first);
  expect(request).toHaveBeenCalledTimes(2);
});

it('does not let an old rejection erase a fresh cache', async () => {
  let reject;
  request.mockReturnValueOnce(new Promise((_, fail) => { reject = fail; })).mockResolvedValue({ models: [] });
  const obsolete = getChatModelsCatalogCached().catch(() => null);
  resetChatModelsCache();
  const current = getChatModelsCatalogCached();
  reject(new Error('unavailable'));
  await obsolete;
  expect(getChatModelsCatalogCached()).toBe(current);
  expect(request).toHaveBeenCalledTimes(2);
});

it('clears failed compatibility discovery for retry', async () => {
  request.mockRejectedValueOnce(new Error('unavailable')).mockResolvedValueOnce([]);
  await expect(getChatModelsCached()).rejects.toThrow('unavailable');
  await getChatModelsCached();
  expect(request).toHaveBeenCalledTimes(2);
});
