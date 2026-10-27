import { act, renderHook, waitFor } from '@testing-library/react';
import { useChatCapabilities } from '../../../../src/features/chat/hooks/orchestration/useChatCapabilities';

jest.mock('../../../../src/shared/api/chat', () => {
  throw new Error('synthetic_capability_module_failure');
});

it('settles a failed capability-module load and keeps explicit retry usable', async () => {
  const { result } = renderHook(() => useChatCapabilities());
  await waitFor(() => expect(result.current.modelsStatus).toBe('error'));
  await act(async () => result.current.refreshModels());
  expect(result.current.modelsStatus).toBe('error');
  expect(result.current.availableModels).toEqual([]);
});
